# Leveling self-test checklist

- [ ] Message XP increments once per cooldown window (same user/channel).
- [ ] Voice XP increments per minute correctly and no double counting after reconnect.
- [ ] Level curve thresholds match expected values for configured curve.
- [ ] Leaderboard query uses indexed sort (`guild_id`, `level`, `xp`) and returns quickly.
- [ ] Disabling leveling (`settings.leveling.enabled=false`) stops message and voice XP gain.
