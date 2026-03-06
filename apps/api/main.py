import uvicorn

from apps.api.shuyuan_core.app import app


def main() -> None:
    uvicorn.run(
        "apps.api.shuyuan_core.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
