"""Create (or update) the Fomy ElevenLabs agent for forma and its client tools.

Usage, with ELEVENLABS_API_KEY in the repo .env:
    python scripts/setup_elevenlabs_agent.py            # creates a new agent, prints its ID
    python scripts/setup_elevenlabs_agent.py --update   # updates ELEVENLABS_AGENT_ID in place
    python scripts/setup_elevenlabs_agent.py --enable-language-selection  # only enables language overrides
Then put the printed ID in .env as ELEVENLABS_AGENT_ID.
"""

import argparse
import os
from pathlib import Path
import sys

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[2] / '.env')

from app.elevenlabs_agent import FIRST_MESSAGE, PROMPT, tool_configs

API = 'https://api.elevenlabs.io/v1/convai'


def enable_language_selection(client, agent_id):
    """Preserve the shared agent's prompt, voice, tools, and other override settings."""
    from copy import deepcopy
    current = client.get(f'{API}/agents/{agent_id}').raise_for_status().json()
    overrides = deepcopy(current.get('platform_settings', {}).get('overrides', {}))
    agent = overrides.setdefault('conversation_config_override', {}).setdefault('agent', {})
    if agent.get('language'):
        return False
    agent['language'] = True
    client.patch(f'{API}/agents/{agent_id}', json={
        'platform_settings': {'overrides': overrides},
    }).raise_for_status()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--update', action='store_true', help='Update the agent in ELEVENLABS_AGENT_ID instead of creating one.')
    parser.add_argument('--enable-language-selection', action='store_true',
                        help='Only enable per-conversation language selection on the existing agent.')
    args = parser.parse_args()
    key = os.environ.get('ELEVENLABS_API_KEY') or sys.exit('Set ELEVENLABS_API_KEY in .env first.')
    agent_id = os.getenv('ELEVENLABS_AGENT_ID')
    if (args.update or args.enable_language_selection) and not agent_id:
        sys.exit('Set ELEVENLABS_AGENT_ID to update an existing agent.')

    with httpx.Client(headers={'xi-api-key': key}, timeout=30) as client:
        if args.enable_language_selection:
            enable_language_selection(client, agent_id)
            print('Per-conversation language selection is enabled.')
            return
        # Reuse tools with the same name so repeated runs don't pile up duplicates.
        existing = {tool['tool_config']['name']: tool['id']
                    for tool in client.get(f'{API}/tools').raise_for_status().json().get('tools', [])}
        tool_ids = []
        for body in tool_configs():
            name = body['tool_config']['name']
            if name in existing:
                client.patch(f'{API}/tools/{existing[name]}', json=body).raise_for_status()
                tool_ids.append(existing[name])
            else:
                tool_ids.append(client.post(f'{API}/tools', json=body).raise_for_status().json()['id'])

        conversation_config = {'agent': {
            'first_message': FIRST_MESSAGE, 'language': 'en',
            # The LLM that runs the conversation; any model ElevenLabs lists for agents.
            'prompt': {'prompt': PROMPT, 'tool_ids': tool_ids, 'llm': os.getenv('ELEVENLABS_AGENT_LLM', 'gemini-2.5-flash')},
        }}
        voice = os.getenv('ELEVENLABS_VOICE_ID')
        if voice:
            conversation_config['tts'] = {'voice_id': voice}
        platform_settings = {'overrides': {'conversation_config_override': {
            'agent': {'first_message': True, 'language': True},
        }}}
        if args.update:
            client.patch(f'{API}/agents/{agent_id}', json={
                'conversation_config': conversation_config, 'platform_settings': platform_settings,
            }).raise_for_status()
            print(f'Updated agent {agent_id} with {len(tool_ids)} tools.')
        else:
            created = client.post(f'{API}/agents/create', json={
                'name': 'Fomy — forma guide', 'conversation_config': conversation_config,
                'platform_settings': platform_settings,
            }).raise_for_status().json()
            print(f"Created agent. Add this to .env:\nELEVENLABS_AGENT_ID={created['agent_id']}")


if __name__ == '__main__':
    main()
