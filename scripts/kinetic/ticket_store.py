"""Ticket store: where a run's tickets live, behind one interface.

The local ticket store keeps tickets in the run's state.json (kinetic's
behavior before ticket stores existed). Any other store is a module named
`kinetic.<kind>_store` exposing `make(config) -> TicketStore`; this module
never names one, so kinetic's core stays independent of every store.
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Protocol

LOCAL = {"kind": "local"}


class TicketStoreError(Exception):
    """A ticket store could not read or write the run's tickets."""


class TicketStore(Protocol):
    def read(self, run_dir, st: dict) -> dict:
        """Every ticket of the run, staged ones included, keyed by ticket id."""

    def write(self, run_dir, st: dict, before: dict, after: dict) -> None:
        """Persist the change from `before` to `after`, fully or not at all."""

    def stage_path(self, run_dir) -> Path | None:
        """Where staged (not yet published) tickets live, or None."""

    def publish(self, run_dir, st: dict) -> dict:
        """Publish staged tickets; returns provisional id -> final id."""

    def touch(self, run_dir, st: dict, ticket_id: str) -> None:
        """Signal that a running ticket's implementer is alive."""

    def health(self, settings: Path) -> list:
        """Doctor rows ({"name", "status", "fix"}) this store needs."""


class LocalTicketStore:
    """Tickets stay in state.json under "tickets"; state.save persists them."""

    def read(self, run_dir, st: dict) -> dict:
        return st.setdefault("tickets", {})

    def write(self, run_dir, st: dict, before: dict, after: dict) -> None:
        return None

    def stage_path(self, run_dir) -> Path | None:
        return None

    def publish(self, run_dir, st: dict) -> dict:
        return {i: i for i in st.get("tickets", {})}

    def touch(self, run_dir, st: dict, ticket_id: str) -> None:
        return None

    def health(self, settings: Path) -> list:
        return []


def _module(kind: str) -> str:
    return f"kinetic.{kind}_store"


def store_for(record: dict | None) -> TicketStore:
    record = record or LOCAL
    kind = record.get("kind", "local")
    if kind == "local":
        return LocalTicketStore()
    # The store mutates this same dict (first-use settings), so save() persists it.
    return importlib.import_module(_module(kind)).make(record.setdefault("config", {}))


def for_state(st: dict) -> TicketStore:
    return store_for(st.get("ticket_store"))


def is_local(st: dict) -> bool:
    return (st.get("ticket_store") or LOCAL).get("kind", "local") == "local"


def for_tracker(tracker: str) -> dict:
    """The ticket_store record for a new run on this tracker."""
    if tracker and tracker != "local" and importlib.util.find_spec(_module(tracker)) is not None:
        return {"kind": tracker, "config": {}}
    return dict(LOCAL)
