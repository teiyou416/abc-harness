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
from dataclasses import dataclass
from pathlib import Path

from abc_harness.agent.model import EFFORTS, MODELS
from abc_harness.agent.session import ChatSession, Turn
from abc_harness.interfaces.console import Write, cost_line, estimated_cost, task_summary

Read = Callable[[str], str]
PROMPT = "› "
HELP = """Type a research request and press Enter (Alt+Enter for a new line). Each request runs as its own task.
  /tasks          list this conversation's tasks
  /model [name]   show the model, or switch the following tasks to another one
  /effort [level] show the effort, or set it for the following tasks
  /status         show the model, effort, limits, tasks, and estimated cost of this conversation
  /new            start a new conversation; the agent forgets the earlier tasks
  /help           show this help
  /quit           leave (or Ctrl-D)
Ctrl-C while a task runs stops that task and returns here."""


@dataclass
class ModelControl:
    """How the chat shows and switches the model and its effort. `switch` and `set_effort` return why they
    refused, or None."""

    current: Callable[[], str]
    switch: Callable[[str], str | None]
    available: Callable[[], list[str]]
    effort: Callable[[], str] | None = None
    set_effort: Callable[[str], str | None] | None = None


def run_chat(
    new_session: Callable[[], ChatSession],
    run_turn: Callable[[ChatSession, str], Turn],
    read: Read,
    write: Write = print,
    show_answers: bool = False,
    models: ModelControl | None = None,
    limits: Callable[[], tuple[float, int]] | None = None,
) -> int:
    """Run the conversation until the researcher leaves. Returns the exit status.

    `show_answers` prints each final answer after its task; leave it off when the live output already shows it.
    `limits` returns the active runtime limit in seconds and the LLM call limit that each following task gets.
    """
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
            elif command == "/status":
                write(_status(session, models, limits))
            elif command == "/new":
                session = new_session()
                write(f"New conversation {session.session_id}; earlier tasks are forgotten.")
            elif command == "/model":
                write(_model_command(models, argument.strip()))
            elif command == "/effort":
                write(_effort_command(models, argument.strip().lower()))
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
        if show_answers and turn.summary:
            write(f"\n{turn.summary.strip()}")
        for out in task_summary(turn.artifact_dir):
            write(out)


def _task_list(session: ChatSession) -> str:
    if not session.turns:
        return "No task yet in this conversation."
    rows = [f"{i}. {t.task_id}  {'reply (no plan)' if t.is_reply else t.status}  {t.model}{f' ({t.effort})' if t.effort else ''}  "
            f"{' '.join(t.question.split())[:60]}"
            for i, t in enumerate(session.turns, 1)]  # fmt: skip
    return "\n".join(rows)


def _status(
    session: ChatSession, models: ModelControl | None, limits: Callable[[], tuple[float, int]] | None
) -> str:
    lines = [f"Conversation {session.session_id} (log: {session.dir / 'session.jsonl'})"]
    if models is not None:
        effort = f", effort {models.effort()}" if models.effort else ""
        lines.append(f"Model: {models.current()}{effort} (for the following tasks)")
    if limits is not None:
        seconds, calls = limits()
        lines.append(f"Limits per task: {seconds:g} s of active runtime, {calls} LLM calls")
    if not session.turns:
        lines.append("Tasks: none yet")
        return "\n".join(lines)
    counts: dict[str, int] = {}
    total, priced, unknown = 0.0, set[str](), set[str]()
    for t in session.turns:
        if not t.is_reply:
            counts[t.status] = counts.get(t.status, 0) + 1
        trace = t.artifact_dir / "trace.jsonl"
        if trace.exists():
            cost, p, u = estimated_cost(trace, t.model)
            total, priced, unknown = total + cost, priced | p, unknown | u
    tasks = sum(counts.values())
    by_status = f" ({', '.join(f'{n} {s}' for s, n in counts.items())})" if tasks else ""
    lines.append(f"Tasks with a plan: {tasks}{by_status}; replies without a plan: {len(session.turns) - tasks}; "
                 "/tasks lists both")  # fmt: skip
    lines.append(cost_line(total, priced, unknown) if priced or unknown else "Estimated cost: no model call yet")
    return "\n".join(lines)


def _model_command(models: ModelControl | None, name: str) -> str:
    if models is None:
        return "! this chat cannot switch models"
    if not name:
        listed = "\n".join(f"  {m}" for m in models.available())
        return f"Model: {models.current()}\nModels:\n{listed}\nSwitch with /model <name>; it applies to the following tasks."
    problem = models.switch(name)
    if problem:
        return f"! {problem}"
    spec = MODELS.get(name)
    note = " It cannot see images: figures in papers and its own figures are not shown to it." if spec and not spec.sees_images else ""
    return f"The following tasks use {name}.{note} Earlier tasks keep the model they ran with."


def _effort_command(models: ModelControl | None, level: str) -> str:
    if models is None or models.effort is None or models.set_effort is None:
        return "! this chat cannot change the effort"
    if not level:
        return (f"Effort: {models.effort()}\nLevels: {', '.join(EFFORTS)}\n"
                "Set it with /effort <level>; it applies to the following tasks.")  # fmt: skip
    if level not in EFFORTS:
        return f"! unknown effort {level!r}; choose one of: {', '.join(EFFORTS)}"
    problem = models.set_effort(level)
    if problem:
        return f"! {problem}"
    return f"The following tasks use effort {level}. Earlier tasks keep the effort they ran with."


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
