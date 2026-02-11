
def must_get_env(key: str, cast=None):
    value = os.getenv(key)
    if value is None:
        raise RuntimeError(f"Environment variable '{key}' is required but not set")

    if cast:
        try:
            return cast(value)
        except ValueError:
            raise RuntimeError(
                f"Environment variable '{key}' must be {cast.__name__}, got '{value}'"
            )

    return value