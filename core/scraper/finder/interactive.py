# /*
#  *  ╔════════════════════════════════════════════════════════════╗
#  *  ║                                                            ║
#  *  ║                     PRIVACY-URL-FINDER                     ║
#  *  ║                                                            ║
#  *  ║                         by Nihal Rodge                     ║
#  *  ║                                                            ║
#  *  ║  GitHub: github.com/MrSpideyNihal/privacy-url-finder       ║
#  *  ║                                                            ║
#  *  ╚════════════════════════════════════════════════════════════╝
#  */
#
# This code was integrated from privacy-url-finder:
# https://github.com/MrSpideyNihal/privacy-url-finder
#

"""Interactive Terminal UI for Privacy URL Finder using Rich."""

import sys
from typing import Optional

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False
    box = None
    Console = None
    Panel = None
    Table = None
    Text = None

from .dataset.manager import DatasetManager
from .finder import PrivacyURLFinder
from .models import PolicyResult, ResolutionStatus


def format_result_panel(res: PolicyResult) -> Panel:
    """Create a rich formatted panel for a resolution result."""
    table = Table(box=None, show_header=False, pad_edge=False)
    table.add_column("Key", style="bold dim", width=16)
    table.add_column("Val", style="bold white")

    # Status styling
    if res.status == ResolutionStatus.FOUND:
        status_text = "[bold black on green] [+] FOUND [/bold black on green]"
    elif res.status == ResolutionStatus.PROBABLE:
        status_text = "[bold black on yellow] [?] PROBABLE [/bold black on yellow]"
    else:
        status_text = "[bold white on red] [x] NOT FOUND [/bold white on red]"

    table.add_row("Status", status_text)
    table.add_row("Target Query", f"[cyan]{res.query}[/cyan]")

    if res.entity_name:
        table.add_row("Entity Name", res.entity_name)

    if res.url:
        table.add_row("Policy URL", f"[bold underline cyan]{res.url}[/bold underline cyan]")
    else:
        table.add_row("Policy URL", "[dim italic]No verified policy URL found[/dim italic]")

    conf_pct = int(res.confidence * 100)
    conf_color = "green" if conf_pct >= 80 else ("yellow" if conf_pct >= 50 else "red")
    table.add_row("Confidence", f"[{conf_color}]{conf_pct}%[/{conf_color}]")

    source_name = res.source.value if res.source else "None"
    table.add_row("Resolution Tier", f"{source_name} [dim]({res.method})[/dim]")

    if res.domain:
        table.add_row("Official Domain", res.domain)

    table.add_row("Elapsed Time", f"{res.elapsed_ms:.1f} ms")

    # Regulated NBFC Partner callout
    if res.metadata and res.metadata.get("regulated_nbfc"):
        nbfc_name = res.metadata["regulated_nbfc"]
        table.add_row(
            "RBI Partner",
            f"[bold black on yellow] NBFC [/bold black on yellow] [yellow]{nbfc_name}[/yellow]",
        )

    # Validation signals
    if res.validation and res.validation.signals:
        sig_str = "\n".join(f"[dim]*[/dim] [green]{s}[/green]" for s in res.validation.signals[:5])
        table.add_row("Verified Signals", sig_str)
    elif res.status == ResolutionStatus.FOUND:
        table.add_row("Verified Signals", "[green]* Curated database entity match[/green]")

    border_color = "green" if res.status == ResolutionStatus.FOUND else ("yellow" if res.status == ResolutionStatus.PROBABLE else "red")
    title = f"[bold {border_color}]PrivUp Resolution Verdict[/bold {border_color}]"

    return Panel(table, title=title, border_style=border_color, box=box.ROUNDED, padding=(1, 2))


def run_interactive_tui():
    """Launch the interactive terminal session."""
    if not _HAS_RICH:
        print("Rich is required for the interactive TUI. Run 'pip install rich' to use it.", file=sys.stderr)
        return
    console = Console()
    finder = PrivacyURLFinder()
    dataset_mgr = DatasetManager()

    welcome_text = Text.from_markup(
        "[bold cyan]PrivUp[/bold cyan] [bold white]Privacy URL Finder[/bold white]\n"
        "[dim]On-device privacy policy discovery & verification engine[/dim]\n\n"
        "[bold yellow]Quick Commands:[/bold yellow]\n"
        "  * Type any service, app, or package: [cyan]KreditBee[/cyan], [cyan]CASHe[/cyan], [cyan]com.kissht[/cyan], [cyan]Spotify[/cyan]\n"
        "  * Type [bold]dataset[/bold] or [bold]cat[/bold] to search catalog (e.g. [cyan]dataset lending[/cyan])\n"
        "  * Type [bold]examples[/bold] to run a demo batch\n"
        "  * Type [bold]exit[/bold] or [bold]q[/bold] to quit"
    )

    console.print(Panel(welcome_text, border_style="cyan", box=box.DOUBLE, padding=(1, 2)))

    while True:
        try:
            console.print("\n[bold cyan]puf[/bold cyan] [dim]>[/dim] ", end="")
            user_input = input().strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Exiting Privacy URL Finder. Stay private![/dim]")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        if cmd in ("exit", "quit", "q"):
            console.print("[dim]Exiting Privacy URL Finder. Stay private![/dim]")
            break

        elif cmd == "help" or cmd == "?":
            console.print("[dim]Enter any company or app name to find its privacy policy URL.[/dim]")
            console.print("[dim]Try: KreditBee, Navi, CASHe, Kissht, CRED, Paytm, Spotify, github.com[/dim]")
            continue

        elif cmd.startswith("dataset") or cmd.startswith("cat"):
            parts = user_input.split(maxsplit=1)
            search_term = parts[1] if len(parts) > 1 else ""
            if search_term:
                matches = dataset_mgr.search(search_term)
                console.print(f"[bold]Found {len(matches)} matches for '{search_term}':[/bold]")
            else:
                matches = dataset_mgr.entries[:15]
                console.print(f"[bold]Showing {len(matches)} of {len(dataset_mgr.entries)} catalog entries:[/bold]")

            table = Table(box=box.SIMPLE_HEAVY)
            table.add_column("Name", style="bold cyan")
            table.add_column("Category", style="yellow")
            table.add_column("Privacy URL", style="green")
            table.add_column("NBFC Partner", style="magenta")

            for m in matches[:20]:
                table.add_row(
                    m["name"],
                    m.get("category", "-"),
                    m.get("privacy_url", "-")[:45] + ("..." if len(m.get("privacy_url", "")) > 45 else ""),
                    m.get("regulated_nbfc", "-") or "-",
                )
            console.print(table)
            continue

        elif cmd == "examples":
            samples = ["KreditBee", "CASHe", "https://github.com", "com.kissht"]
            for s in samples:
                with console.status(f"[bold green]Resolving '{s}'...[/bold green]"):
                    res = finder.find(s)
                console.print(format_result_panel(res))
            continue

        # Normal single query resolution
        with console.status(f"[bold green]Discovering policy for '{user_input}'...[/bold green]"):
            res = finder.find(user_input)

        console.print(format_result_panel(res))


if __name__ == "__main__":
    run_interactive_tui()
