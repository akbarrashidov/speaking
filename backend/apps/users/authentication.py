from rest_framework import authentication, exceptions

from .jwt_utils import TokenError, get_user_from_token


class JWTAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1")
        if not header:
            return None
        parts = header.split()
        if parts[0].lower() != self.keyword.lower():
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Authorization sarlavhasi noto'g'ri")
        try:
            user = get_user_from_token(parts[1])
        except TokenError as exc:
            raise exceptions.AuthenticationFailed(str(exc)) from exc
        return (user, None)

    def authenticate_header(self, request):
        return self.keyword
