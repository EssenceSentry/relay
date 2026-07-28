from __future__ import annotations

import ast
from pathlib import Path


class _RuntimeImportVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.aws_lambda_typing_imports: list[str] = []

    def visit_If(self, node: ast.If) -> None:
        if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.aws_lambda_typing_imports.extend(
            alias.name
            for alias in node.names
            if alias.name.startswith("aws_lambda_typing")
        )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if (node.module or "").startswith("aws_lambda_typing"):
            self.aws_lambda_typing_imports.append(str(node.module))


def test_inbound_email_handler_keeps_typing_package_out_of_runtime() -> None:
    handler = (
        Path(__file__).parents[1]
        / "services"
        / "inbound_email_lambda"
        / "handler.py"
    )
    tree = ast.parse(handler.read_text(encoding="utf-8"))
    visitor = _RuntimeImportVisitor()

    visitor.visit(tree)

    assert visitor.aws_lambda_typing_imports == []


def test_inbound_email_image_packages_runtime_dependencies() -> None:
    requirements = (
        Path(__file__).parents[1]
        / "services"
        / "inbound_email_lambda"
        / "requirements.txt"
    ).read_text(encoding="utf-8")

    assert "boto3" in requirements
    assert "pydantic" in requirements
