"""
API Test Generator
==================
Reads an OpenAPI JSON file and generates pytest test cases
that verify each endpoint returns a 200 status code.

Usage:
    python api_test_generator.py openapi.json
"""

import json
import sys


def load_openapi_spec(filepath: str) -> dict:
    """Load and parse the OpenAPI JSON file from disk."""
    with open(filepath, "r") as f:
        return json.load(f)


def get_base_url(spec: dict) -> str:
    """
    Extract the base URL from the OpenAPI spec.
    OpenAPI 3.x uses 'servers'; Swagger 2.x uses 'host' + 'basePath'.
    Falls back to localhost if nothing is defined.
    """
    # OpenAPI 3.x
    if "servers" in spec and spec["servers"]:
        return spec["servers"][0]["url"].rstrip("/")

    # Swagger 2.x
    if "host" in spec:
        scheme = spec.get("schemes", ["http"])[0]
        base_path = spec.get("basePath", "")
        return f"{scheme}://{spec['host']}{base_path}".rstrip("/")

    # Fallback
    return "http://localhost"


def get_first_example_param(param: dict) -> str:
    """
    Return a placeholder value for a path parameter, e.g. {id} → "1".
    Uses the example field if present, otherwise picks a sensible default
    based on the parameter's declared type.
    """
    schema = param.get("schema", param)  # Swagger 2 inlines schema; OAS3 nests it

    # Use an explicit example if the spec provides one
    if "example" in param:
        return str(param["example"])
    if "example" in schema:
        return str(schema["example"])

    # Pick a default based on type
    param_type = schema.get("type", "string")
    if param_type == "integer":
        return "1"
    if param_type == "number":
        return "1.0"
    if param_type == "boolean":
        return "true"
    return "example"


def resolve_path_params(path: str, parameters: list) -> str:
    """
    Replace every {param} placeholder in the path with a concrete value
    so the generated test hits a real URL, e.g. /users/{id} → /users/1.
    """
    path_params = [p for p in parameters if p.get("in") == "path"]
    for param in path_params:
        placeholder = "{" + param["name"] + "}"
        value = get_first_example_param(param)
        path = path.replace(placeholder, value)
    return path


def collect_endpoints(spec: dict) -> list[dict]:
    """
    Walk every path × method combination in the spec and return a flat list
    of endpoint descriptors that the test generator will use.

    Each descriptor contains:
        - method  : HTTP verb (get, post, …)
        - path    : raw path string from the spec
        - test_path: path with {placeholders} filled in
        - summary : human-readable label for the test name
    """
    endpoints = []
    paths = spec.get("paths", {})

    for path, path_item in paths.items():
        # Collect parameters defined at the path level (shared by all methods)
        path_level_params = path_item.get("parameters", [])

        # Iterate over every HTTP method defined for this path
        for method, operation in path_item.items():
            # Skip non-method keys like 'parameters', 'summary', etc.
            if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue

            # Merge path-level and operation-level parameters
            operation_params = operation.get("parameters", [])
            all_params = path_level_params + operation_params

            # Fill in path placeholders for the test URL
            test_path = resolve_path_params(path, all_params)

            # Use the operation summary (or a fallback) as the test label
            summary = operation.get("summary", f"{method.upper()} {path}")

            endpoints.append({
                "method": method,
                "path": path,
                "test_path": test_path,
                "summary": summary,
            })

    return endpoints


def make_test_name(method: str, path: str) -> str:
    """
    Convert a method + path into a valid Python function name.
    Example: GET /users/{id}/orders  →  test_get_users_id_orders
    """
    # Replace path separators and special chars with underscores
    clean = path.replace("/", "_").replace("{", "").replace("}", "").replace("-", "_")
    # Collapse consecutive underscores and strip leading ones
    parts = [p for p in clean.split("_") if p]
    return f"test_{method}_{'_'.join(parts)}"


def generate_test_file(base_url: str, endpoints: list[dict]) -> str:
    """
    Build the full content of test_api.py as a string.
    Each endpoint gets its own pytest test function.
    """
    lines = []

    # ── File header ──────────────────────────────────────────────────────────
    lines.append('"""')
    lines.append("Auto-generated API tests.")
    lines.append("Run with:  pytest test_api.py -v")
    lines.append('"""')
    lines.append("")
    lines.append("import requests")
    lines.append("import pytest")
    lines.append("")
    lines.append("")

    # ── Base URL fixture ──────────────────────────────────────────────────────
    lines.append("# Change BASE_URL if your server runs on a different host/port.")
    lines.append(f'BASE_URL = "{base_url}"')
    lines.append("")
    lines.append("")

    # ── One test per endpoint ─────────────────────────────────────────────────
    for ep in endpoints:
        test_name = make_test_name(ep["method"], ep["path"])
        full_url = f'{{BASE_URL}}{ep["test_path"]}'
        http_method = ep["method"].lower()

        lines.append(f"def {test_name}():")
        lines.append(f'    """Test: {ep["summary"]}"""')
        lines.append(f'    url = f"{full_url}"')
        lines.append(f"    response = requests.{http_method}(url)")
        lines.append("")
        lines.append("    # Assert the endpoint is reachable and returns success")
        lines.append("    assert response.status_code == 200, (")
        lines.append(f'        f"Expected 200 from {ep["method"].upper()} {ep["path"]}, "')
        lines.append('        f"got {response.status_code}"')
        lines.append("    )")
        lines.append("")
        lines.append("")

    return "\n".join(lines)


def main():
    # ── Argument handling ─────────────────────────────────────────────────────
    if len(sys.argv) < 2:
        print("Usage: python api_test_generator.py <openapi.json>")
        sys.exit(1)

    openapi_file = sys.argv[1]

    # ── Load spec ─────────────────────────────────────────────────────────────
    print(f"📂  Reading OpenAPI spec: {openapi_file}")
    spec = load_openapi_spec(openapi_file)

    # ── Extract info ──────────────────────────────────────────────────────────
    base_url = get_base_url(spec)
    print(f"🌐  Base URL: {base_url}")

    endpoints = collect_endpoints(spec)
    print(f"🔍  Found {len(endpoints)} endpoint(s)")

    if not endpoints:
        print("⚠️  No endpoints found. Check your OpenAPI file.")
        sys.exit(1)

    # ── Generate & write test file ────────────────────────────────────────────
    test_code = generate_test_file(base_url, endpoints)

    output_file = "test_api.py"
    with open(output_file, "w") as f:
        f.write(test_code)

    print(f"✅  Tests written to {output_file}")
    print(f"    Run them with:  pytest {output_file} -v")


if __name__ == "__main__":
    main()
