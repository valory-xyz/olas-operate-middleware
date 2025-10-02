# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""Exceptions."""

from http import HTTPStatus


class ResourceException(Exception):
    """Base resource exceptio."""

    code: int


class BadRequest(ResourceException):
    """Bad request error."""

    code = HTTPStatus.BAD_REQUEST


class ResourceAlreadyExists(ResourceException):
    """Bad request error."""

    code = HTTPStatus.CONFLICT


class NotFound(ResourceException):
    """Not found error."""

    code = HTTPStatus.NOT_FOUND


class NotAllowed(ResourceException):
    """Not allowed error."""

    code = HTTPStatus.METHOD_NOT_ALLOWED
