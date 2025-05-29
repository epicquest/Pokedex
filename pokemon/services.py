# pokemon/services.py
import requests
import logging
from typing import Dict, List, Optional, Tuple
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache
from .models import Pokemon, PokemonType, PokemonAbility, PokemonAbilityLink, EvolutionChain, Evolution

logger = logging.getLogger(__name__)


class PokeAPIService:
    BASE_URL = "https://pokeapi.co/api/v2"
    CACHE_TIMEOUT = 3600  # 1 hour

    @classmethod
    def _make_request(cls, endpoint: str) -> Optional[Dict]:
        """Make a request to PokeAPI with error handling and caching."""
        cache_key = f"pokeapi_{endpoint.replace('/', '_')}"
        cached_data = cache.get(cache_key)

        if cached_data:
            return cached_data

        try:
            url = f"{cls.BASE_URL}/{endpoint.lstrip('/')}"
            logger.info(f"Making PokeAPI request: {url}")

            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()
            cache.set(cache_key, data, cls.CACHE_TIMEOUT)
            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"PokeAPI request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in PokeAPI request: {e}")
            return None

    @classmethod
    def fetch_pokemon_list(cls, limit: int = 151, offset: int = 0) -> Optional[List[Dict]]:
        """Fetch a list of Pokemon from the API."""
        endpoint = f"pokemon?limit={limit}&offset={offset}"
        return cls._make_request(endpoint)

    @classmethod
    def fetch_pokemon_detail(cls, pokemon_id: int) -> Optional[Dict]:
        """Fetch detailed information about a specific Pokemon."""
        endpoint = f"pokemon/{pokemon_id}"
        return cls._make_request(endpoint)

    @classmethod
    def fetch_pokemon_species(cls, pokemon_id: int) -> Optional[Dict]:
        """Fetch species information for a Pokemon."""
        endpoint = f"pokemon-species/{pokemon_id}"
        return cls._make_request(endpoint)

    @classmethod
    def fetch_evolution_chain(cls, chain_id: int) -> Optional[Dict]:
        """Fetch evolution chain data."""
        endpoint = f"evolution-chain/{chain_id}"
        return cls._make_request(endpoint)

    @classmethod
    def fetch_type_data(cls, type_name: str) -> Optional[Dict]:
        """Fetch type information."""
        endpoint = f"type/{type_name}"
        return cls._make_request(endpoint)

    @classmethod
    def fetch_ability_data(cls, ability_name: str) -> Optional[Dict]:
        """Fetch ability information."""
        endpoint = f"ability/{ability_name}"
        return cls._make_request(endpoint)


class PokemonDataManager:
    """Manages Pokemon data synchronization between API and database."""

    TYPE_COLORS = {
        'normal': '#A8A878',
        'fire': '#F08030',
        'water': '#6890F0',
        'electric': '#F8D030',
        'grass': '#78C850',
        'ice': '#98D8D8',
        'fighting': '#C03028',
        'poison': '#A040A0',
        'ground': '#E0C068',
        'flying': '#A890F0',
        'psychic': '#F85888',
        'bug': '#A8B820',
        'rock': '#B8A038',
        'ghost': '#705898',
        'dragon': '#7038F8',
        'dark': '#705848',
        'steel': '#B8B8D0',
        'fairy': '#EE99AC',
    }

    @classmethod
    def sync_pokemon_types(cls):
        """Sync Pokemon types with the database."""
        for type_name, color in cls.TYPE_COLORS.items():
            PokemonType.objects.get_or_create(
                name=type_name,
                defaults={'color': color}
            )

    @classmethod
    def create_or_update_pokemon(cls, pokemon_data: Dict, species_data: Optional[Dict] = None) -> Optional[Pokemon]:
        """Create or update a Pokemon record from API data."""
        try:
            # Extract basic info
            pokedex_id = pokemon_data['id']
            name = pokemon_data['name']
            height = pokemon_data['height']
            weight = pokemon_data['weight']
            base_experience = pokemon_data.get('base_experience', 0)

            # Extract sprites
            sprites = pokemon_data.get('sprites', {})
            sprite_front = sprites.get('front_default')
            sprite_back = sprites.get('back_default')
            official_artwork = sprites.get('other', {}).get('official-artwork', {}).get('front_default')

            # Extract stats
            stats = {stat['stat']['name']: stat['base_stat'] for stat in pokemon_data['stats']}

            # Determine if legendary/mythical from species data
            is_legendary = species_data.get('is_legendary', False) if species_data else False
            is_mythical = species_data.get('is_mythical', False) if species_data else False

            # Create or update Pokemon
            pokemon, created = Pokemon.objects.update_or_create(
                pokedex_id=pokedex_id,
                defaults={
                    'name': name,
                    'height': height,
                    'weight': weight,
                    'sprite_front': sprite_front,
                    'sprite_back': sprite_back,
                    'official_artwork': official_artwork,
                    'hp': stats.get('hp', 50),
                    'attack': stats.get('attack', 50),
                    'defense': stats.get('defense', 50),
                    'special_attack': stats.get('special-attack', 50),
                    'special_defense': stats.get('special-defense', 50),
                    'speed': stats.get('speed', 50),
                    'base_experience': base_experience,
                    'is_legendary': is_legendary,
                    'is_mythical': is_mythical,
                    'api_data_cached_at': timezone.now(),
                }
            )

            # Handle types
            pokemon.types.clear()
            for type_info in pokemon_data.get('types', []):
                type_name = type_info['type']['name']
                pokemon_type, _ = PokemonType.objects.get_or_create(
                    name=type_name,
                    defaults={'color': cls.TYPE_COLORS.get(type_name, '#000000')}
                )
                pokemon.types.add(pokemon_type)

            # Handle abilities
            PokemonAbilityLink.objects.filter(pokemon=pokemon).delete()
            for ability_info in pokemon_data.get('abilities', []):
                ability_name = ability_info['ability']['name']
                is_hidden = ability_info.get('is_hidden', False)
                slot = ability_info.get('slot', 1)

                ability, _ = PokemonAbility.objects.get_or_create(
                    name=ability_name,
                    defaults={'is_hidden': is_hidden}
                )

                PokemonAbilityLink.objects.create(
                    pokemon=pokemon,
                    ability=ability,
                    is_hidden=is_hidden,
                    slot=slot
                )

            logger.info(f"{'Created' if created else 'Updated'} Pokemon: {pokemon}")
            return pokemon

        except Exception as e:
            logger.error(f"Error creating/updating Pokemon: {e}")
            return None

    @classmethod
    def sync_pokemon_batch(cls, limit: int = 151, offset: int = 0) -> List[Pokemon]:
        """Sync a batch of Pokemon from the API."""
        pokemon_list = PokeAPIService.fetch_pokemon_list(limit, offset)
        if not pokemon_list:
            return []

        synced_pokemon = []
        for pokemon_info in pokemon_list.get('results', []):
            # Extract ID from URL
            pokemon_id = int(pokemon_info['url'].rstrip('/').split('/')[-1])

            # Fetch detailed data
            pokemon_data = PokeAPIService.fetch_pokemon_detail(pokemon_id)
            species_data = PokeAPIService.fetch_pokemon_species(pokemon_id)

            if pokemon_data:
                pokemon = cls.create_or_update_pokemon(pokemon_data, species_data)
                if pokemon:
                    synced_pokemon.append(pokemon)

        return synced_pokemon

    @classmethod
    def get_pokemon_stats_comparison(cls, pokemon1_id: int, pokemon2_id: int) -> Optional[Dict]:
        """Compare stats between two Pokemon."""
        try:
            pokemon1 = Pokemon.objects.get(pokedex_id=pokemon1_id)
            pokemon2 = Pokemon.objects.get(pokedex_id=pokemon2_id)

            stats_comparison = {
                'pokemon1': {
                    'name': pokemon1.name,
                    'id': pokemon1.pokedex_id,
                    'sprite': pokemon1.sprite_front,
                    'stats': {
                        'hp': pokemon1.hp,
                        'attack': pokemon1.attack,
                        'defense': pokemon1.defense,
                        'special_attack': pokemon1.special_attack,
                        'special_defense': pokemon1.special_defense,
                        'speed': pokemon1.speed,
                        'total': pokemon1.total_stats
                    }
                },
                'pokemon2': {
                    'name': pokemon2.name,
                    'id': pokemon2.pokedex_id,
                    'sprite': pokemon2.sprite_front,
                    'stats': {
                        'hp': pokemon2.hp,
                        'attack': pokemon2.attack,
                        'defense': pokemon2.defense,
                        'special_attack': pokemon2.special_attack,
                        'special_defense': pokemon2.special_defense,
                        'speed': pokemon2.speed,
                        'total': pokemon2.total_stats
                    }
                }
            }

            # Calculate differences
            stats_comparison['differences'] = {}
            for stat in ['hp', 'attack', 'defense', 'special_attack', 'special_defense', 'speed', 'total']:
                diff = stats_comparison['pokemon1']['stats'][stat] - stats_comparison['pokemon2']['stats'][stat]
                stats_comparison['differences'][stat] = diff

            return stats_comparison

        except Pokemon.DoesNotExist:
            return None