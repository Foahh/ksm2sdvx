"""Shared CLI presentation; domain code must not depend on this module."""

import sys

from ksm2sdvx.common.diagnostics import Diagnostic, Severity


def print_diagnostics(diagnostics: tuple[Diagnostic, ...]) -> None:
    for diagnostic in diagnostics:
        if diagnostic.severity != Severity.INFO:
            print(
                f"{diagnostic.severity.value}: {diagnostic.code} {diagnostic.json_pointer}: {diagnostic.message}",
                file=sys.stderr,
            )
