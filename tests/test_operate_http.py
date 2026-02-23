# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""Tests for operate/operate_http/__init__.py."""

from http import HTTPStatus

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from operate.operate_http import Resource
from operate.operate_http.exceptions import NotAllowed


class _ConcreteResource(Resource):
    """Minimal concrete Resource used across tests."""

    def __init__(self) -> None:
        """Initialise resource."""
        super().__init__()

    @property
    def json(self) -> dict:  # type: ignore[override]
        """Return test JSON payload."""
        return {"data": "value"}

    def create(self, data: dict) -> dict:  # type: ignore[override]
        """Create resource."""
        return {"created": data}

    def update(self, data: dict) -> dict:  # type: ignore[override]
        """Update resource."""
        return {"updated": data}

    def delete(self, data: dict) -> dict:  # type: ignore[override]
        """Delete resource."""
        return {"deleted": data}


class TestResourceBaseClassMethods:
    """Tests for Resource base-class default method stubs (lines 62, 77, 82-110)."""

    def test_init_populates_handlers_dict(self) -> None:
        """Test __init__ sets up all four HTTP method handlers (line 62)."""
        resource = _ConcreteResource()
        assert set(resource._handlers) == {"GET", "POST", "PUT", "DELETE"}

    async def test_access_raises_value_error(self) -> None:
        """Test base access() raises ValueError with correct message (line 77)."""
        resource = Resource.__new__(Resource)  # type: ignore[abstract]
        Resource.__init__(resource)
        with pytest.raises(ValueError, match="No resource identifer defined"):
            await resource.access({}, scope={}, receive=None, send=None)  # type: ignore[arg-type]

    def test_json_property_raises_not_allowed(self) -> None:
        """Test base json property raises NotAllowed (line 82)."""
        resource = Resource.__new__(Resource)  # type: ignore[abstract]
        Resource.__init__(resource)
        with pytest.raises(NotAllowed):
            _ = resource.json

    def test_create_raises_not_allowed(self) -> None:
        """Test base create() raises NotAllowed (line 86)."""
        resource = Resource.__new__(Resource)  # type: ignore[abstract]
        Resource.__init__(resource)
        with pytest.raises(NotAllowed):
            resource.create({})

    def test_update_raises_not_allowed(self) -> None:
        """Test base update() raises NotAllowed (line 90)."""
        resource = Resource.__new__(Resource)  # type: ignore[abstract]
        Resource.__init__(resource)
        with pytest.raises(NotAllowed):
            resource.update({})

    def test_delete_raises_not_allowed(self) -> None:
        """Test base delete() raises NotAllowed (line 94)."""
        resource = Resource.__new__(Resource)  # type: ignore[abstract]
        Resource.__init__(resource)
        with pytest.raises(NotAllowed):
            resource.delete({})

    def test_get_returns_json_property(self) -> None:
        """Test _get() delegates to json property (line 98)."""
        resource = _ConcreteResource()
        assert resource._get() == {"data": "value"}

    def test_post_calls_create_with_data(self) -> None:
        """Test _post() delegates to create with payload (line 102)."""
        resource = _ConcreteResource()
        assert resource._post({"k": "v"}) == {"created": {"k": "v"}}  # type: ignore[arg-type]

    def test_put_calls_update_with_data(self) -> None:
        """Test _put() delegates to update with payload (line 106)."""
        resource = _ConcreteResource()
        assert resource._put({"k": "v"}) == {"updated": {"k": "v"}}  # type: ignore[arg-type]

    def test_delete_calls_delete_with_data(self) -> None:
        """Test _delete() delegates to delete with payload (line 110)."""
        resource = _ConcreteResource()
        assert resource._delete({"id": 1}) == {"deleted": {"id": 1}}  # type: ignore[arg-type]


class TestResourceAsgiCallHandler:
    """Tests for Resource.__call__ ASGI handler (lines 114-147)."""

    def test_get_request_returns_json_property(self) -> None:
        """Test GET request returns the json property (lines 114-134)."""
        client = TestClient(_ConcreteResource())
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"data": "value"}

    def test_post_with_valid_json_calls_create(self) -> None:
        """Test POST with valid JSON body calls create (lines 125-134)."""
        client = TestClient(_ConcreteResource())
        response = client.post("/", json={"name": "test"})
        assert response.status_code == 200
        assert response.json() == {"created": {"name": "test"}}

    def test_post_with_invalid_json_defaults_to_empty_dict(self) -> None:
        """Test POST with malformed JSON defaults data to empty dict (lines 127-129)."""
        client = TestClient(_ConcreteResource())
        response = client.post(
            "/",
            content=b"not-valid-json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 200
        assert response.json() == {"created": {}}

    def test_put_calls_update(self) -> None:
        """Test PUT request calls update with request body (lines 130-134)."""
        client = TestClient(_ConcreteResource())
        response = client.put("/", json={"field": "new"})
        assert response.status_code == 200
        assert response.json() == {"updated": {"field": "new"}}

    def test_delete_calls_delete_method(self) -> None:
        """Test DELETE request calls delete with request body (lines 130-134)."""
        client = TestClient(_ConcreteResource())
        # TestClient.delete() doesn't accept body kwargs; use request() instead.
        response = client.request("DELETE", "/", json={"id": 99})
        assert response.status_code == 200
        assert response.json() == {"deleted": {"id": 99}}

    def test_resource_exception_returns_error_response_with_correct_status(
        self,
    ) -> None:
        """Test ResourceException is caught and returns the exception's HTTP status (lines 135-139)."""

        class _FailResource(Resource):
            def __init__(self) -> None:
                super().__init__()

            @property
            def json(self) -> dict:  # type: ignore[override]
                raise NotAllowed("Access denied")

        client = TestClient(_FailResource())
        response = client.get("/")
        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
        assert response.json()["error"] == "Access denied"

    def test_generic_exception_returns_500_with_traceback(self) -> None:
        """Test unhandled exceptions return HTTP 500 with traceback body (lines 140-146)."""

        class _BrokenResource(Resource):
            def __init__(self) -> None:
                super().__init__()

            @property
            def json(self) -> dict:  # type: ignore[override]
                raise RuntimeError("Something broke badly")

        client = TestClient(_BrokenResource(), raise_server_exceptions=False)
        response = client.get("/")
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        body = response.json()
        assert "Something broke badly" in body["error"]
        assert "traceback" in body

    def test_path_params_delegates_to_access(self) -> None:
        """Test request with path params calls access() and returns early (lines 115-121)."""

        class _PathResource(Resource):
            def __init__(self) -> None:
                super().__init__()
                self.accessed_params: dict = {}

            async def access(  # type: ignore[override]
                self,
                params: dict,
                scope: object,
                receive: object,
                send: object,
            ) -> None:
                """Handle parameterised path access."""
                self.accessed_params = params
                resp = JSONResponse({"accessed": True, "params": params})
                await resp(scope, receive, send)  # type: ignore[arg-type]

        resource = _PathResource()
        app = Starlette(routes=[Route("/{item_id}", endpoint=resource)])
        client = TestClient(app)
        response = client.get("/42")
        assert response.status_code == 200
        assert response.json()["accessed"] is True
        assert resource.accessed_params == {"item_id": "42"}
