"""Unit-тесты для app.agent.tools.calculator."""

import pytest

from app.tools.calculator import calculator


# ===========================================================================
# Успешные вычисления
# ===========================================================================

class TestCalculatorSuccess:
    @pytest.mark.parametrize(
        "expression,expected",
        [
            ("2 + 2", "4"),
            ("10 - 3", "7"),
            ("6 * 7", "42"),
            ("10 / 4", "2.5"),
            ("2 ** 10", "1024"),
            ("10 % 3", "1"),
            ("-5 + 3", "-2"),
            ("+5", "5"),
            ("(123 + 456) * 7", "4053"),
            ("((2 + 3) * (4 - 1)) ** 2", "225"),
            ("1.5 + 2.5", "4.0"),
        ],
    )
    def test_valid_expressions(self, expression: str, expected: str) -> None:
        # У @tool-декорированной функции есть .invoke() для прямого вызова
        result = calculator.invoke({"expression": expression})
        assert result == expected


# ===========================================================================
# Отклонение опасных выражений
# ===========================================================================

class TestCalculatorRejects:
    @pytest.mark.parametrize(
        "expression",
        [
            "__import__('os').system('echo hi')",
            "open('/etc/passwd').read()",
            "eval('1+1')",
            "exec('x=1')",
            "lambda: 1",
            "[1, 2, 3]",
            "{'a': 1}",
            "a + b",
            "print(1)",
            "1 if True else 2",
            "x = 5",
            "1; import os",
        ],
    )
    def test_dangerous_expressions_rejected(self, expression: str) -> None:
        result = calculator.invoke({"expression": expression})
        assert result.startswith("Error:"), f"Ожидали ошибку для: {expression}"

    def test_syntax_error_rejected(self) -> None:
        result = calculator.invoke({"expression": "2 +"})
        assert result.startswith("Error:")


# ===========================================================================
# Прямой тест _eval_node
# ===========================================================================

class TestEvalNode:
    def test_division_by_zero_propagates_as_error(self) -> None:
        # ZeroDivisionError не должен убивать процесс — калькулятор вернёт Error
        result = calculator.invoke({"expression": "1 / 0"})
        assert result.startswith("Error:")

    def test_nested_parentheses(self) -> None:
        result = calculator.invoke({"expression": "((1 + 2) * (3 + 4))"})
        assert result == "21"