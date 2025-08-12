from sotd.auth import get_spotify_client


def main() -> None:
    sp = get_spotify_client()
    me = sp.current_user()
    print(f"Authenticated as: {me.get('id')} ({me.get('display_name')})")


if __name__ == "__main__":
    main()
