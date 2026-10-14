"""Desktop assistant core."""

# B-new: source-run fallback for bundled_version(); _version.txt is
# gitignored, so a checkout without this set to the release version made
# is_newer() always True and the update banner show on every launch.
# Bump in the same commit that moves the release tag.
__version__ = "0.2.4"
