"""Test-only FastAPI composition for deterministic Compose smoke tests."""

from decision_assistant.main import create_app
from decision_assistant.providers.factory import (
    ProviderBundle,
    get_provider_bundle_factory,
)
from tests.support.smoke_provider import (
    SmokeEmbeddingProvider,
    SmokeGenerationProvider,
)

app = create_app()
_bundle = ProviderBundle(
    embedding=SmokeEmbeddingProvider(),
    generation=SmokeGenerationProvider(),
)
app.dependency_overrides[get_provider_bundle_factory] = lambda: lambda: _bundle
