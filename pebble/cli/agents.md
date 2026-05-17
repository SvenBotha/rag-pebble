# pebble/cli/ — Agent Context

Typer CLI. Two call paths:
- **Admin commands** (`ingest`, `delete`, `compact`, `pods`) → call `build_services()` directly via `asyncio.run`. No server needed.
- **Query commands** (`ask`, `chat`, `tui`) → HTTP calls to the API server.

## Key pattern for admin commands

```python
@app.command()
def my_command(config: Path | None = typer.Option(None, "--config")) -> None:
    async def _wrapped() -> None:
        services = _load_services(config)
        try:
            # do the work
        finally:
            await services.aclose()
    try:
        asyncio.run(_wrapped())
    except PebbleError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=1) from e
```

Never `import asyncio.run` at module level — only call it inside command functions.

## `--pod` flag (to add to all commands)

All commands should accept `--pod <name>` which overrides `config.storage.active_pod` before building services:

```python
def _load_services(config_path: Path | None, pod: str | None = None) -> Services:
    config = load_config(config_path)
    if pod is not None:
        config = config.model_copy(update={"storage": config.storage.model_copy(update={"active_pod": pod})})
    return build_services(config)
```

## Commands to add

### `pebble pods` subcommand group

```python
pods_app = typer.Typer(help="Manage document store pods.")
app.add_typer(pods_app, name="pods")

@pods_app.command("list")
def pods_list(): ...          # print table of pods with chunk counts

@pods_app.command("create")
def pods_create(name: str): ...   # create new pod directory

@pods_app.command("delete")
def pods_delete(name: str): ...   # confirm then delete

@pods_app.command("switch")
def pods_switch(name: str): ...   # write active_pod to config.yaml
```

### `pebble tui` command

```python
@app.command()
def tui(api_url: str | None = typer.Option(None, "--api-url")) -> None:
    """Launch the interactive TUI."""
    from pebble.tui.app import PebbleApp
    PebbleApp(api_url=_api_url(api_url)).run()
```

Lazy import (`from pebble.tui.app import ...`) keeps CLI startup fast for users who don't have `textual` installed, or shows a clear error.

## `--debug` flag convention

`pebble ask` already has `--debug` which prints chunks + assembled prompt. Any new query-adjacent commands should follow the same pattern: off by default, explicit opt-in.
