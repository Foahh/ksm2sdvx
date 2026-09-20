"""Typed VOX script expressions and assignments."""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ksm2sdvx.chart.errors import ConversionError
from ksm2sdvx.chart.vox.values import finite, integer

if TYPE_CHECKING:
    from ksm2sdvx.chart.vox.model import VoxPosition


class ScriptVariable(StrEnum):
    TARGET_STEP = "$targetStep"
    OFFSET_X = "$offsetX"
    OFFSET_Y = "$offsetY"


class ScriptConstant(StrEnum):
    CURRENT_STEP = "$currentStep"


class ArithmeticOperator(StrEnum):
    ADD = "+"
    SUBTRACT = "-"
    MULTIPLY = "*"
    DIVIDE = "/"


class ComparisonOperator(StrEnum):
    EQUAL = "=="
    NOT_EQUAL = "!="
    GREATER = ">"
    LESS = "<"
    GREATER_EQUAL = ">="
    LESS_EQUAL = "<="


@dataclass(frozen=True, slots=True)
class ScriptNumber:
    value: int | float
    float_suffix: bool = False


@dataclass(frozen=True, slots=True)
class BinaryExpression:
    left: Expression
    operator: ArithmeticOperator
    right: Expression


type Expression = ScriptNumber | ScriptVariable | ScriptConstant | BinaryExpression


@dataclass(frozen=True, slots=True)
class ScriptCondition:
    left: Expression
    operator: ComparisonOperator
    right: Expression


@dataclass(frozen=True, slots=True)
class Assignment:
    variable: ScriptVariable
    expression: Expression
    when: ScriptCondition | None = None


@dataclass(frozen=True, slots=True)
class Script:
    identifier: int
    assignments: tuple[Assignment, ...]


@dataclass(frozen=True, slots=True)
class ScriptApplication:
    position: VoxPosition
    script_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ScriptedTrack:
    number: int
    applications: tuple[ScriptApplication, ...]


def expression_text(expression: Expression) -> str:
    if isinstance(expression, (ScriptVariable, ScriptConstant)):
        return expression.value
    if isinstance(expression, ScriptNumber):
        finite(expression.value)
        if type(expression.float_suffix) is not bool:
            raise ConversionError("Invalid script number suffix")
        if round(expression.value, 3) != expression.value:
            raise ConversionError("Script numbers support at most three decimal places")
        number = (
            str(expression.value)
            if type(expression.value) is int
            else f"{expression.value:.3f}".rstrip("0").rstrip(".")
        )
        return number + ("f" if expression.float_suffix else "")
    if type(expression) is not BinaryExpression:
        raise ConversionError("Invalid script expression")
    if type(expression.operator) is not ArithmeticOperator:
        raise ConversionError("Invalid script arithmetic operator")
    return (
        f"( {expression_text(expression.left)} {expression.operator.value} "
        f"{expression_text(expression.right)} )"
    )


def assignment_text(assignment: Assignment) -> str:
    if type(assignment.variable) is not ScriptVariable:
        raise ConversionError("Invalid script assignment target")
    result = f"{assignment.variable.value} = {expression_text(assignment.expression)}"
    condition = assignment.when
    if condition is not None:
        if type(condition.operator) is not ComparisonOperator:
            raise ConversionError("Invalid script comparison operator")
        result += (
            f" when {expression_text(condition.left)} {condition.operator.value} "
            f"{expression_text(condition.right)}"
        )
    return result


def script_lines(script: Script) -> tuple[str, ...]:
    integer(script.identifier)
    return (
        f"@SCRIPTSTART {script.identifier}",
        *(assignment_text(a) for a in script.assignments),
        "@SCRIPTEND",
    )
