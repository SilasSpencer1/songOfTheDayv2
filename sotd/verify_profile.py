from sotd.auth import get_spotify_client
from sotd.profile import get_user_profile


def main() -> None:
    sp = get_spotify_client()
    profile = get_user_profile(sp)
    print("Top artists:", [a["name"] for a in profile["top_artists"]])
    print("Top tracks:", [t["name"] for t in profile["top_tracks"]])
    print("Recent tracks:", [t["name"] for t in profile["recent_tracks"]])
    print("Known artists:", len(profile["known_artists"]))
    print("Known tracks:", len(profile["known_tracks"]))


if __name__ == "__main__":
    main()
