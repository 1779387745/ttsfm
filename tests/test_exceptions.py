from ttsfm.exceptions import AuthenticationException, create_exception_from_response


def test_create_exception_string_error_field():
    exc = create_exception_from_response(401, {"error": "Invalid API key"})
    assert isinstance(exc, AuthenticationException)
    assert exc.message == "Invalid API key"


def test_create_exception_dict_error_field():
    exc = create_exception_from_response(401, {"error": {"message": "bad"}})
    assert isinstance(exc, AuthenticationException)
    assert exc.message == "bad"


def test_create_exception_missing_error_uses_default():
    exc = create_exception_from_response(401, {})
    assert isinstance(exc, AuthenticationException)
    assert exc.message == "API request failed"
