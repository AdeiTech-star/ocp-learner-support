"""Flag → nudge routing.

Single source of truth mapping detection flags to the template and
nudge_type that should be used to respond. Update here when new flags
or templates are added.
"""
from typing import Literal, NamedTuple

FlagCode = Literal["R1", "R2", "R3", "Y1", "Y1b", "Y2", "Y3", "Y4"]
Severity = Literal["red", "yellow"]
NudgeType = Literal[
    "reengagement", "late_submission", "gate_ahead",
    "activity_no_work", "score_dropping",
]


class NudgeRoute(NamedTuple):
    template_name: str          # Jinja filename without extension
    nudge_type: NudgeType       # for nudge_events.nudge_type
    severity: Severity          # passed into the template context


_ROUTING: dict[str, NudgeRoute] = {
    "R1":  NudgeRoute("reengagement",     "reengagement",     "red"),
    "Y1":  NudgeRoute("reengagement",     "reengagement",     "yellow"),
    "R2":  NudgeRoute("late_submission",  "late_submission",  "red"),
    "Y2":  NudgeRoute("late_submission",  "late_submission",  "yellow"),
    "Y3":  NudgeRoute("late_submission",  "late_submission",  "yellow"),
    "R3":  NudgeRoute("gate_ahead",       "gate_ahead",       "red"),
    "Y1b": NudgeRoute("activity_no_work", "activity_no_work", "yellow"),
    "Y4":  NudgeRoute("score_dropping",   "score_dropping",   "yellow"),
}


def route_for_flag(flag_code: str) -> NudgeRoute:
    """Return the template + nudge_type + severity for a given flag code.

    Raises KeyError if the flag code isn't mapped — better to fail loudly
    than to silently pick a default template.
    """
    try:
        return _ROUTING[flag_code]
    except KeyError:
        raise KeyError(
            f"No routing configured for flag_code={flag_code!r}. "
            f"Known codes: {sorted(_ROUTING)}"
        ) from None