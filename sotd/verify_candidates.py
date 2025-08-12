from sotd.auth import get_spotify_client
from sotd.profile import get_user_profile
from sotd.candidates import generate_candidates, filter_candidates_by_mood


def main() -> None:
    sp = get_spotify_client()
    profile = get_user_profile(sp)
    candidates = generate_candidates(sp, profile)
    print(f"Found {len(candidates)} candidate tracks")

    # Show a few raw candidates
    if candidates:
        track_objs = sp.tracks(candidates[:10]).get("tracks", [])
        for t in track_objs:
            try:
                name = t.get("name")
                artists = ", ".join(a.get("name") for a in (t.get("artists") or []))
                print(f"- {name} — {artists}")
            except Exception:
                continue

    # Example: mood filtering
    mood = "happy"
    filtered = filter_candidates_by_mood(candidates, mood=mood, top_k=5)
    if filtered:
        print(f"\nTop {len(filtered)} '{mood}' candidates:")
        f_objs = sp.tracks(filtered).get("tracks", [])
        for t in f_objs:
            try:
                name = t.get("name")
                artists = ", ".join(a.get("name") for a in (t.get("artists") or []))
                print(f"* {name} — {artists}")
            except Exception:
                continue


if __name__ == "__main__":
    main()
