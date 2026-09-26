import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from presence_mirror import (
    activities_signature,
    extract_session_list,
    mirrorable_session_activities,
    normalize_presence_activities,
)


class PresenceMirrorTests(unittest.TestCase):
    def test_normalizes_immediate_presence_activity(self):
        activities = normalize_presence_activities(
            [
                {
                    "id": "spotify:1",
                    "session_id": "remote-session",
                    "name": "Spotify",
                    "type": 2,
                    "details": "New track",
                }
            ]
        )

        self.assertEqual(
            activities,
            [{"name": "Spotify", "type": 2, "details": "New track"}],
        )

    def test_empty_presence_activity_clears_playback(self):
        self.assertEqual(normalize_presence_activities([]), [])

    def test_mirrors_local_spotify_activity(self):
        payload = [
            {"session_id": "railway", "activities": []},
            {
                "session_id": "local-pc",
                "activities": [
                    {
                        "id": "source-activity",
                        "session_id": "local-pc",
                        "created_at": 1790240000000,
                        "name": "Spotify",
                        "type": 2,
                        "details": "Example Song",
                        "state": "Example Artist",
                        "sync_id": "track-1",
                        "assets": {
                            "large_image": "spotify:image-1",
                            "large_text": "Example Album",
                        },
                    }
                ],
            },
        ]

        mirrored = mirrorable_session_activities(payload, "railway")

        self.assertEqual(len(mirrored), 1)
        self.assertEqual(mirrored[0]["name"], "Spotify")
        self.assertEqual(mirrored[0]["type"], 2)
        self.assertEqual(mirrored[0]["details"], "Example Song")
        self.assertNotIn("id", mirrored[0])
        self.assertNotIn("session_id", mirrored[0])
        self.assertNotIn("created_at", mirrored[0])

    def test_ignores_current_session_and_hidden_activities(self):
        payload = [
            {
                "session_id": "railway",
                "activities": [{"name": "Spotify", "type": 2}],
                "hidden_activities": [{"name": "Hidden Game", "type": 0}],
            }
        ]

        self.assertEqual(mirrorable_session_activities(payload, "railway"), [])

    def test_accepts_ready_payload_shape(self):
        payload = {
            "session_id": "railway",
            "sessions": [
                {
                    "session_id": "local-pc",
                    "activities": [{"name": "Spotify", "type": 2}],
                }
            ],
        }

        self.assertEqual(extract_session_list(payload)[0]["session_id"], "local-pc")
        self.assertEqual(
            len(mirrorable_session_activities(payload, "railway")),
            1,
        )

    def test_signatures_are_stable(self):
        first = [{"name": "Spotify", "type": 2}]
        second = [{"type": 2, "name": "Spotify"}]

        self.assertEqual(activities_signature(first), activities_signature(second))


if __name__ == "__main__":
    unittest.main()
