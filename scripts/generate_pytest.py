#!/usr/bin/env python3
"""
AgentOps — Automated Pytest Boilerplate Generator
==================================================
Usage:
  python scripts/generate_pytest.py --router apps/api-gateway/app/routers/tools.py

This script parses any FastAPI router file using python's AST module, extracts
the router endpoints (GET, POST, PATCH, etc.), and generates a fully scaffolded,
premium, robust Pytest test suite, integrated with boilerplate mocks.
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
from pathlib import Path


class RouteVisitor(ast.NodeVisitor):
    """AST visitor to extract router decorators and endpoint metadata."""

    def __init__(self):
        self.routes = []
        self.prefix = ""

    def visit_Assign(self, node: ast.Assign):
        # Detect: router = APIRouter(prefix="/tools", ...)
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "router"
        ):
            if (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "APIRouter"
            ):
                for kw in node.value.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        self.prefix = kw.value.value
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        for decorator in node.decorator_list:
            # Check for router.get, router.post, etc.
            if self._is_router_decorator(decorator):
                http_method, path = self._parse_decorator(decorator)
                if http_method:
                    self.routes.append(
                        {
                            "name": node.name,
                            "method": http_method,
                            "path": path,
                            "args": [
                                arg.arg
                                for arg in node.args.args
                                if arg.arg not in ("db", "user", "self", "_rl")
                            ],
                            "body_param": self._get_body_param_class(node),
                        }
                    )
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.visit_FunctionDef(node)

    def _is_router_decorator(self, decorator) -> bool:
        # Case: @router.get(...)
        if isinstance(decorator, ast.Call) and isinstance(
            decorator.func, ast.Attribute
        ):
            if (
                isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "router"
            ):
                return True
        return False

    def _parse_decorator(self, decorator: ast.Call) -> tuple[str | None, str | None]:
        # Method: e.g. "get", "post"
        method = decorator.func.attr.upper()
        # Path: first positional argument, or keyword argument "path"
        path = "/"
        if decorator.args:
            first_arg = decorator.args[0]
            if isinstance(first_arg, ast.Constant):
                path = first_arg.value
        else:
            for kw in decorator.keywords:
                if kw.arg == "path" and isinstance(kw.value, ast.Constant):
                    path = kw.value
        return method, path

    def _get_body_param_class(self, node: ast.FunctionDef) -> str | None:
        # Tries to find parameters typed with custom names e.g., ToolInvokeRequest
        for arg in node.args.args:
            if arg.arg == "body" and arg.annotation:
                if isinstance(arg.annotation, ast.Name):
                    return arg.annotation.id
            # Fallback check if parameter name itself is descriptive and has class annotation
            elif arg.annotation and isinstance(arg.annotation, ast.Name):
                if arg.annotation.id.endswith("Request") or arg.annotation.id.endswith(
                    "Create"
                ):
                    return arg.annotation.id
        return None


def generate_boilerplate_code(router_name: str, routes: list[dict], prefix: str) -> str:
    """Compiles list of routes into standard premium pytest boilerplate code."""
    module_class_name = f"Test{router_name.title()}Router"

    output = []
    output.append(f'"""')
    output.append(f"Generated Pytest Suite for {router_name.title()} Router")
    output.append(f"=============================================")
    output.append(f"This suite covers standard routing integration, security blocks,")
    output.append(f"invalid payloads, and operational CRUD patterns.")
    output.append(f'"""')
    output.append(f"from __future__ import annotations")
    output.append(f"")
    output.append(f"import uuid")
    output.append(f"import pytest")
    output.append(f"from httpx import AsyncClient")
    output.append(f"from sqlalchemy.ext.asyncio import AsyncSession")
    output.append(f"")
    output.append(f"# Importing standardized premium mocks for test execution")
    output.append(
        f"from tests.boilerplate_mocks import MockAsyncSession, MockRedisClient, MockLLMClient"
    )
    output.append(f"")
    output.append(f"")
    output.append(f"@pytest.mark.asyncio")
    output.append(f"class {module_class_name}:")
    output.append(f"")

    for route in routes:
        name = route["name"]
        method = route["method"]
        path = route["path"]
        body_param = route["body_param"] or "dict"

        # Transform router path template e.g., "/{tool_id}" -> f"/{{tool_id}}"
        path_str = path
        path_interpolated = False
        if "{" in path and "}" in path:
            path_interpolated = True
            # Simple replace to allow f-string
            path_str = path.replace("{", "{").replace("}", "}")

        # Prepend prefix to the URL, making sure no duplicate slashes are created.
        full_prefix = f"/api/v1{prefix}"
        if path_str == "" or path_str == "/":
            url_base = full_prefix
        elif path_str.startswith("/") and full_prefix.endswith("/"):
            url_base = f"{full_prefix[:-1]}{path_str}"
        elif path_str.startswith("/") or full_prefix.endswith("/"):
            url_base = f"{full_prefix}{path_str}"
        else:
            url_base = f"{full_prefix}/{path_str}"

        # 1. Success Path
        output.append(f"    async def test_{name}_success(")
        output.append(f"        self, client: AsyncClient, db_session: AsyncSession")
        output.append(f"    ):")
        output.append(f'        """')
        output.append(f"        Success track for {method} {path}")
        output.append(f'        """')
        if path_interpolated:
            # Generate a mock uuid or mock name for placeholder
            var_name = path.split("{")[1].split("}")[0]
            output.append(f"        mock_{var_name} = uuid.uuid4()")
            output.append(
                f'        url = "{url_base}".replace("{path}", str(mock_{var_name}))'
            )
        else:
            output.append(f'        url = "{url_base}"')

        # Request call block
        if method == "POST" or method == "PUT" or method == "PATCH":
            output.append(
                f"        payload = {{}}  # TODO: Populate with simulated {body_param}"
            )
            output.append(
                f"        resp = await client.{method.lower()}(url, json=payload)"
            )
        else:
            output.append(f"        resp = await client.{method.lower()}(url)")

        output.append(f"        # Assert response characteristics")
        output.append(f"        assert resp.status_code in (200, 201, 202)")
        output.append(f"        data = resp.json()")
        output.append(f"        assert data is not None")
        output.append(f"")

        # 2. Unauthorized Block
        output.append(f"    async def test_{name}_unauthorized(")
        output.append(f"        self, anon_client: AsyncClient")
        output.append(f"    ):")
        output.append(f'        """')
        output.append(f"        Unauthenticated block ensuring API token compliance")
        output.append(f'        """')
        if path_interpolated:
            var_name = path.split("{")[1].split("}")[0]
            output.append(
                f'        url = "{url_base}".replace("{path}", str(uuid.uuid4()))'
            )
        else:
            output.append(f'        url = "{url_base}"')

        if method in ("POST", "PUT", "PATCH"):
            output.append(
                f"        resp = await anon_client.{method.lower()}(url, json={{}})"
            )
        else:
            output.append(f"        resp = await anon_client.{method.lower()}(url)")

        output.append(f"        assert resp.status_code == 401")
        output.append(f"")

        # 3. Validation / Error block for operations with inputs
        if method in ("POST", "PUT", "PATCH") and body_param != "dict":
            output.append(f"    async def test_{name}_invalid_payload(")
            output.append(f"        self, client: AsyncClient")
            output.append(f"    ):")
            output.append(f'        """')
            output.append(
                f"        Malformed body triggers standard 422 Unprocessable entity response"
            )
            output.append(f'        """')
            if path_interpolated:
                output.append(
                    f'        url = "{url_base}".replace("{path}", str(uuid.uuid4()))'
                )
            else:
                output.append(f'        url = "{url_base}"')

            # Empty payload or mismatched types
            output.append(f'        invalid_payload = {{"invalid_key_trigger": True}}')
            output.append(
                f"        resp = await client.{method.lower()}(url, json=invalid_payload)"
            )
            output.append(f"        assert resp.status_code == 422")
            output.append(f"")

    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description="AgentOps Pytest Boilerplate Code Scaffolder."
    )
    parser.add_argument(
        "--router",
        type=str,
        required=True,
        help="Absolute or relative path to the FastAPI router python file.",
    )
    parser.add_argument(
        "--output", type=str, help="Target location to write the generated pytest file."
    )
    args = parser.parse_args()

    router_path = Path(args.router)
    if not router_path.exists():
        print(
            f"Error: Target router file '{router_path}' does not exist.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Parsing AST for router: {router_path}...")
    try:
        content = router_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except Exception as e:
        print(
            f"FATAL: Could not parse target AST structure. Error: {e}", file=sys.stderr
        )
        sys.exit(1)

    visitor = RouteVisitor()
    visitor.visit(tree)

    if not visitor.routes:
        print(
            f"Warning: No routes decorated with '@router.<method>' found in the provided file."
        )
        sys.exit(0)

    print(f"Detected {len(visitor.routes)} route(s):")
    for r in visitor.routes:
        print(f"  - {r['method']} {r['path']} -> {r['name']}()")

    router_name = router_path.stem
    generated_code = generate_boilerplate_code(
        router_name, visitor.routes, visitor.prefix
    )

    output_path = args.output
    if not output_path:
        # Check parents to find where a 'tests' directory exists
        tests_dir = None
        for parent in router_path.parents:
            candidate = parent / "tests"
            if candidate.exists() and candidate.is_dir():
                tests_dir = candidate
                break
        if tests_dir:
            output_path = tests_dir / f"test_generated_{router_name}.py"
        else:
            output_path = router_path.parent / f"test_{router_name}.py"

    output_path = Path(output_path)
    print(f"Writing fully mocked pytest file to: {output_path}...")
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(generated_code, encoding="utf-8")
        print("Success! Test boilerplate generated successfully.")
    except Exception as e:
        print(f"Error writing to output file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
