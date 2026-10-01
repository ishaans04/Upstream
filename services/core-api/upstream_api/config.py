from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    catchment_id: str = "catch-1"
    groq_api_key: str = ""
    hapi_base_url: str = "http://hapi:8080/fhir"
    media_s3_endpoint: str = ""
    media_s3_bucket: str = "upstream-media"
    media_s3_access_key: str = ""
    media_s3_secret_key: str = ""
    open_meteo_base_url: str = "https://api.open-meteo.com/v1"
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""
    snap_max_distance_m: float = 150.0
    network_artifact: str = "data/artifacts/network.npz"
    tables_artifact: str = "data/artifacts/tables.npz"
    # Streams whose posteriors open episodes and whose timers run. `live` always; add
    # `sim` to drive a simulated incident through the real lifecycle (the demo).
    episode_streams: str = "live"
    # The catchment's local time zone: the nightly report runs after 02:00 there.
    catchment_tz: str = "Asia/Kolkata"
    # Phase 11. The MVP's token key (security.py); empty refuses every token.
    jwt_signing_key: str = ""
    # Keys the observer pseudonyms in research exports; empty refuses to export.
    export_pseudonym_key: str = ""

    @property
    def episode_stream_list(self) -> list[str]:
        streams = [s.strip() for s in self.episode_streams.split(",") if s.strip()]
        unknown = set(streams) - {"live", "sim"}
        if unknown:
            raise ValueError(f"EPISODE_STREAMS names unknown streams: {sorted(unknown)}")
        return streams or ["live"]

    # Real environment variables win over .env, which is what lets the host test run
    # point DATABASE_URL at localhost while .env keeps the in-compose db:5432 value.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
