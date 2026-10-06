"""Create a private deployment secret without replacing an existing configuration."""
import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
folder = root / '.secrets'
folder.mkdir(mode=0o700, exist_ok=True)
os.chmod(folder, 0o700)
secret = folder / 'access-token'
if not secret.exists():
    with secret.open('x') as f:
        f.write(secrets.token_urlsafe(48) + '\n')
    # Compose mounts the file read-only for the non-root container user. The host
    # parent directory stays owner-only, so other host users cannot traverse it.
    os.chmod(secret, 0o444)
env = root / '.env'
if not env.exists():
    with env.open('x') as f:
        f.write((root / '.env.example').read_text())
print('Deployment configuration ready. Existing secrets/settings were preserved.')
print('Run docker compose up --build -d. Use the token in .secrets/access-token to sign in.')
