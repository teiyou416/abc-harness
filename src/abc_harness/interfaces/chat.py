"""`abc-harness chat`: a scrolling conversation in the terminal, one task per request.

The loop reads a line, runs slash commands itself, and sends anything else to
the chat session, which runs it as a new task. Ctrl-C during a task stops
that task (its containers are removed and its report is written) and returns
to the prompt; Ctrl-C or Ctrl-D at an empty prompt leaves the chat. Input is
a callable so tests can drive the loop without a terminal; the command line
passes a prompt_toolkit session with history.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from abc_harness.agent.session import ChatSession, Turn
from abc_harness.execution.runner import DockerRunner, RunnerError
from abc_harness.interfaces.console import Write, task_summary
from abc_harness.literature.pdf import PARSER_IMAGE

Read = Callable[[str], str]
PROMPT = "› "
HELP = """Type a research request and press Enter (Alt+Enter for a new line). Each request runs as its own task.
  /tasks          list this conversation's tasks
  /paper <pdf>    add a paper for the agent to read in every following task
  /new            start a new conversation; the agent forgets the earlier tasks
  /help           show this help
  /quit           leave (or Ctrl-D)
Ctrl-C while a task runs stops that task and returns here."""


def check_papers(papers: list[Path], parser_check: Callable[[], None] | None = None) -> str | None:
    """Why the given PDF files cannot be used, or None. Checked before any task starts."""
    for path in papers:
        if not path.is_file():
            return f"{path}: no such file"
        with path.open("rb") as f:
            if f.read(5) != b"%PDF-":
                return f"{path}: not a PDF file"
    if papers:
        try:
            (parser_check or (lambda: DockerRunner().image_info(PARSER_IMAGE)))()
        except RunnerError:
            return f"reading a PDF needs the PDF parser image {PARSER_IMAGE}; run `abc-harness image build --only pdf-parser`"
    return None


def run_chat(
    new_session: Callable[[], ChatSession],
    run_turn: Callable[[ChatSession, str], Turn],
    read: Read,
    write: Write = print,
    parser_check: Callable[[], None] | None = None,
) -> int:
    """Run the conversation until the researcher leaves. Returns the exit status."""
    session = new_session()
    write(f"Conversation {session.session_id} (log: {session.dir / 'session.jsonl'}). /help lists the commands.")
    while True:
        try:
            line = read(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            write("Bye.")
            return 0
        if not line:
            continue
        if line.startswith("/"):
            command, _, argument = line.partition(" ")
            if command in ("/quit", "/exit"):
                write("Bye.")
                return 0
            if command == "/help":
                write(HELP)
            elif command == "/tasks":
                write(_task_list(session))
            elif command == "/new":
                session = new_session()
                write(f"New conversation {session.session_id}; earlier tasks are forgotten. Papers are cleared too.")
            elif command == "/paper":
                path = Path(argument.strip()).expanduser()
                problem = check_papers([path], parser_check) if argument.strip() else "usage: /paper <file.pdf>"
                if problem:
                    write(f"! {problem}")
                else:
                    session.papers.append(path)
                    write(f"Added {path.name}; every following task in this conversation reads it.")
            else:
                write(f"! unknown command {command}; /help lists the commands")
            continue
        try:
            turn = run_turn(session, line)
        except KeyboardInterrupt:
            last = session.turns[-1] if session.turns else None
            where = f" Its report: {last.artifact_dir / 'report.md'}" if last else ""
            write(f"\n! Stopped the task; its containers were removed.{where}")
            continue
        if turn.summary:
            write(f"\n{turn.summary.strip()}")
        for out in task_summary(turn.artifact_dir):
            write(out)


def _task_list(session: ChatSession) -> str:
    if not session.turns:
        return "No task yet in this conversation."
    rows = [f"{i}. {t.task_id}  {t.status}  {' '.join(t.question.split())[:70]}" for i, t in enumerate(session.turns, 1)]
    papers = f"\nPapers: {', '.join(p.name for p in session.papers)}" if session.papers else ""
    return "\n".join(rows) + papers


def terminal_reader(history_file: Path) -> Read:
    """A prompt_toolkit line reader: history with the arrow keys, Enter sends, Alt+Enter (Esc Enter) adds a line."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings

    bindings = KeyBindings()

    @bindings.add("escape", "enter")
    def _(event):  # type: ignore[no-untyped-def]
        event.current_buffer.insert_text("\n")

    history_file.parent.mkdir(parents=True, exist_ok=True)
    prompt = PromptSession(history=FileHistory(str(history_file)), key_bindings=bindings)
    return lambda message: prompt.prompt(message)
