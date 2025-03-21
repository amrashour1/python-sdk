from typing import Callable

from pydantic import AnyHttpUrl
from starlette.routing import Route

from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.handlers.register import RegistrationHandler
from mcp.server.auth.handlers.revoke import RevocationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import OAuthServerProvider
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthMetadata


def validate_issuer_url(url: AnyHttpUrl):
    """
    Validate that the issuer URL meets OAuth 2.0 requirements.

    Args:
        url: The issuer URL to validate

    Raises:
        ValueError: If the issuer URL is invalid
    """

    # RFC 8414 requires HTTPS, but we allow localhost HTTP for testing
    if (
        url.scheme != "https"
        and url.host != "localhost"
        and not (url.host is not None and url.host.startswith("127.0.0.1"))
    ):
        raise ValueError("Issuer URL must be HTTPS")

    # No fragments or query parameters allowed
    if url.fragment:
        raise ValueError("Issuer URL must not have a fragment")
    if url.query:
        raise ValueError("Issuer URL must not have a query string")


AUTHORIZATION_PATH = "/authorize"
TOKEN_PATH = "/token"
REGISTRATION_PATH = "/register"
REVOCATION_PATH = "/revoke"


def create_auth_routes(
    provider: OAuthServerProvider,
    issuer_url: AnyHttpUrl,
    service_documentation_url: AnyHttpUrl | None = None,
    client_registration_options: ClientRegistrationOptions | None = None,
    revocation_options: RevocationOptions | None = None,
) -> list[Route]:
    validate_issuer_url(issuer_url)

    client_registration_options = (
        client_registration_options or ClientRegistrationOptions()
    )
    revocation_options = revocation_options or RevocationOptions()
    metadata = build_metadata(
        issuer_url,
        service_documentation_url,
        client_registration_options,
        revocation_options,
    )
    client_authenticator = ClientAuthenticator(provider)

    # Create routes
    routes = [
        Route(
            "/.well-known/oauth-authorization-server",
            endpoint=MetadataHandler(metadata).handle,
            methods=["GET"],
        ),
        Route(
            AUTHORIZATION_PATH,
            endpoint=AuthorizationHandler(provider).handle,
            methods=["GET", "POST"],
        ),
        Route(
            TOKEN_PATH,
            endpoint=TokenHandler(provider, client_authenticator).handle,
            methods=["POST"],
        ),
    ]

    if client_registration_options.enabled:
        registration_handler = RegistrationHandler(
            provider,
            options=client_registration_options,
        )
        routes.append(
            Route(
                REGISTRATION_PATH,
                endpoint=registration_handler.handle,
                methods=["POST"],
            )
        )

    if revocation_options.enabled:
        revocation_handler = RevocationHandler(provider, client_authenticator)
        routes.append(
            Route(REVOCATION_PATH, endpoint=revocation_handler.handle, methods=["POST"])
        )

    return routes


def modify_url_path(url: AnyHttpUrl, path_mapper: Callable[[str], str]) -> AnyHttpUrl:
    return AnyHttpUrl.build(
        scheme=url.scheme,
        username=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        path=path_mapper(url.path or ""),
        query=url.query,
        fragment=url.fragment,
    )


def build_metadata(
    issuer_url: AnyHttpUrl,
    service_documentation_url: AnyHttpUrl | None,
    client_registration_options: ClientRegistrationOptions,
    revocation_options: RevocationOptions,
) -> OAuthMetadata:
    authorization_url = modify_url_path(
        issuer_url, lambda path: path.rstrip("/") + AUTHORIZATION_PATH.lstrip("/")
    )
    token_url = modify_url_path(
        issuer_url, lambda path: path.rstrip("/") + TOKEN_PATH.lstrip("/")
    )
    # Create metadata
    metadata = OAuthMetadata(
        issuer=issuer_url,
        authorization_endpoint=authorization_url,
        token_endpoint=token_url,
        scopes_supported=None,
        response_types_supported=["code"],
        response_modes_supported=None,
        grant_types_supported=["authorization_code", "refresh_token"],
        token_endpoint_auth_methods_supported=["client_secret_post"],
        token_endpoint_auth_signing_alg_values_supported=None,
        service_documentation=service_documentation_url,
        ui_locales_supported=None,
        op_policy_uri=None,
        op_tos_uri=None,
        introspection_endpoint=None,
        code_challenge_methods_supported=["S256"],
    )

    # Add registration endpoint if supported
    if client_registration_options.enabled:
        metadata.registration_endpoint = modify_url_path(
            issuer_url, lambda path: path.rstrip("/") + REGISTRATION_PATH.lstrip("/")
        )

    # Add revocation endpoint if supported
    if revocation_options.enabled:
        metadata.revocation_endpoint = modify_url_path(
            issuer_url, lambda path: path.rstrip("/") + REVOCATION_PATH.lstrip("/")
        )
        metadata.revocation_endpoint_auth_methods_supported = ["client_secret_post"]

    return metadata
