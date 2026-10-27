from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_role_key: str
    # Required for years, never read: tokens are verified by a round trip to
    # Supabase (auth.py), and the signing keys are asymmetric anyway. Optional
    # now so a producer's own copy has one less secret to find.
    supabase_jwt_secret: str = ""
    anthropic_api_key: str
    sendgrid_api_key: str
    sendgrid_from_email: str
    support_email: str = "support@set-ready-set.com"   # where "Need help?" + waitlist submissions are sent
    app_base_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000"
    # Optional regex matching additional allowed origins, for Vercel preview
    # deployments — every preview gets its own hostname, so a fixed list can only
    # ever cover the one branch alias someone remembered to add. Starlette applies
    # this with re.fullmatch, so the pattern must match the whole origin; escape
    # the dots (\\.) or they match any character. Empty disables it.
    cors_origin_regex: str = ""
    sentry_dsn: str = ""               # optional; set to enable error monitoring
    owner_user_ids: str = ""           # comma-separated auth user ids allowed into Master Access; empty = nobody

    # ── A producer's own copy (docs/own-copy-plan.md) ──────────────────────
    # SINGLE_OWNER=1: this backend belongs to one person. The first-run setup
    # route creates them (routers/setup.py), every request must come from them
    # (auth.get_current_user), and Jobs is simply on. Off, nothing changes for
    # the hosted site. PUBLIC_URL is the one address a copy has — it stands in
    # for APP_BASE_URL and is added to CORS_ORIGINS, so the template asks for
    # one value, not two that have to agree.
    single_owner: bool = False
    public_url: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    def model_post_init(self, __context) -> None:
        url = self.public_url.strip().rstrip("/")
        if url:
            self.app_base_url = url
            origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
            if url not in origins:
                origins.append(url)
            self.cors_origins = ",".join(origins)


settings = Settings()
