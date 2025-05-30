import random

from django.core.paginator import Paginator
from django.shortcuts import redirect

from django.views.generic import ListView, DetailView
from django.views.decorators.http import require_http_methods
from django.db.models import Q
from django.urls import reverse

from .models import Pokemon, PokemonType, UserFavorite, Evolution, EvolutionChain
from .services import PokemonDataManager
import logging

logger = logging.getLogger(__name__)

class PokemonListView(ListView):
    model = Pokemon
    template_name = 'pokemon/pokemon_list.html'
    context_object_name = 'pokemon_list'
    paginate_by = 20

    def get_queryset(self):
        queryset = Pokemon.objects.select_related().prefetch_related('types', 'ability_links__ability')

        # Search functionality
        search_query = self.request.GET.get('search', '').strip()
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(pokedex_id__icontains=search_query)
            )

        # Type filtering
        type_filter = self.request.GET.get('type', '').strip()
        if type_filter:
            queryset = queryset.filter(types__name=type_filter)

        # Generation filtering (basic - first 151 is Gen 1)
        generation = self.request.GET.get('generation', '').strip()
        if generation == '1':
            queryset = queryset.filter(pokedex_id__lte=151)
        elif generation == '2':
            queryset = queryset.filter(pokedex_id__range=(152, 251))

        # Sorting
        sort_by = self.request.GET.get('sort', 'pokedex_id')
        if sort_by in ['pokedex_id', 'name', 'hp', 'attack', 'defense', 'speed']:
            if self.request.GET.get('reverse') == 'true':
                sort_by = f'-{sort_by}'
            queryset = queryset.order_by(sort_by)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['pokemon_types'] = PokemonType.objects.all().order_by('name')
        context['current_search'] = self.request.GET.get('search', '')
        context['current_type'] = self.request.GET.get('type', '')
        context['current_generation'] = self.request.GET.get('generation', '')
        context['current_sort'] = self.request.GET.get('sort', 'pokedex_id')
        context['is_reverse'] = self.request.GET.get('reverse') == 'true'
        return context


# class PokemonDetailView(DetailView):
#     model = Pokemon
#     template_name = 'pokemon/pokemon_detail.html'
#     context_object_name = 'pokemon'
#     slug_field = 'pokedex_id'
#     slug_url_kwarg = 'pokedex_id'
#
#     def get_context_data(self, **kwargs):
#         context = super().get_context_data(**kwargs)
#         pokemon = self.get_object()
#
#         # Get evolution data (simplified - you might want to implement proper evolution chains)
#         context['evolutions'] = Pokemon.objects.filter(
#             pokedex_id__in=[pokemon.pokedex_id - 1, pokemon.pokedex_id + 1]
#         ).exclude(pokedex_id=pokemon.pokedex_id)
#
#         # Check if this Pokemon is in favorites
#         session_key = self.request.session.session_key
#         if session_key:
#             context['is_favorite'] = UserFavorite.objects.filter(
#                 session_key=session_key,
#                 pokemon=pokemon
#             ).exists()
#         else:
#             context['is_favorite'] = False
#
#         # Get related Pokemon (same type)
#         context['related_pokemon'] = Pokemon.objects.filter(
#             types__in=pokemon.types.all()
#         ).exclude(id=pokemon.id).distinct()[:6]
#
#         return context
#


class PokemonDetailView(DetailView):
    model = Pokemon
    template_name = 'pokemon/pokemon_detail.html'
    context_object_name = 'pokemon'

    def get_object(self, queryset=None):
        """
        Get Pokemon by either pk or pokedex_id
        Supports URLs like /pokemon/25/ or /pokemon/pikachu/
        """
        if queryset is None:
            queryset = self.get_queryset()

        # Try to get by pk first (for URLs like /pokemon/1/)
        pk = self.kwargs.get(self.pk_url_kwarg)
        slug = self.kwargs.get(self.slug_url_kwarg)

        if pk is not None:
            # Check if pk is numeric (could be pokedex_id)
            try:
                pk_int = int(pk)
                # Try to get by primary key first, then by pokedex_id
                try:
                    return queryset.get(pk=pk_int)
                except Pokemon.DoesNotExist:
                    return get_object_or_404(queryset, pokedex_id=pk_int)
            except ValueError:
                # pk is not numeric, treat as name
                return get_object_or_404(queryset, name__iexact=pk)

        if slug is not None:
            # Get by name (case-insensitive)
            return get_object_or_404(queryset, name__iexact=slug)

        raise AttributeError(
            f"Generic detail view {self.__class__.__name__} must be called with "
            f"either an object pk or a slug in the URLconf."
        )

    def get_queryset(self):
        """
        Optimize queryset with select_related and prefetch_related
        """
        return Pokemon.objects.select_related().prefetch_related(
            'types',
            'ability_links__ability',
            'evolves_from__from_pokemon__types',
            'evolves_to__to_pokemon__types',
            'evolution_chains__evolutions__to_pokemon'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pokemon = self.object

        # Get evolution chain information
        evolution_data = self.get_evolution_data(pokemon)
        context.update(evolution_data)

        # Get related Pokemon (same types)
        context['related_pokemon'] = self.get_related_pokemon(pokemon)

        # Get stats for visualization (percentages)
        context['stats_percentages'] = self.get_stats_percentages(pokemon)

        # Check if user has favorited this Pokemon (using session)
        session_key = self.request.session.session_key
        if session_key:
            from .models import UserFavorite
            context['is_favorited'] = UserFavorite.objects.filter(
                session_key=session_key,
                pokemon=pokemon
            ).exists()
        else:
            context['is_favorited'] = False

        # Add navigation to previous/next Pokemon
        context['prev_pokemon'] = Pokemon.objects.filter(
            pokedex_id__lt=pokemon.pokedex_id
        ).order_by('-pokedex_id').first()

        context['next_pokemon'] = Pokemon.objects.filter(
            pokedex_id__gt=pokemon.pokedex_id
        ).order_by('pokedex_id').first()

        return context

    def get_evolution_data(self, pokemon):
        """
        Get comprehensive evolution chain data
        """
        evolution_data = {
            'pre_evolutions': [],
            'evolutions': [],
            'evolution_chain': None
        }

        # Get evolutions FROM this Pokemon
        evolutions_from = Evolution.objects.filter(
            from_pokemon=pokemon
        ).select_related('to_pokemon').prefetch_related('to_pokemon__types')

        evolution_data['evolutions'] = [
            {
                'pokemon': evo.to_pokemon,
                'trigger': evo.trigger,
                'min_level': evo.min_level,
                'item': evo.item,
                'condition': evo.condition,
            }
            for evo in evolutions_from
        ]

        # Get evolutions TO this Pokemon (pre-evolutions)
        evolutions_to = Evolution.objects.filter(
            to_pokemon=pokemon
        ).select_related('from_pokemon').prefetch_related('from_pokemon__types')

        evolution_data['pre_evolutions'] = [
            {
                'pokemon': evo.from_pokemon,
                'trigger': evo.trigger,
                'min_level': evo.min_level,
                'item': evo.item,
                'condition': evo.condition,
            }
            for evo in evolutions_to
        ]

        # Get full evolution chain if available
        try:
            chain = EvolutionChain.objects.filter(
                Q(base_pokemon=pokemon) |
                Q(evolutions__from_pokemon=pokemon) |
                Q(evolutions__to_pokemon=pokemon)
            ).prefetch_related(
                'evolutions__from_pokemon__types',
                'evolutions__to_pokemon__types'
            ).first()

            if chain:
                evolution_data['evolution_chain'] = chain
        except EvolutionChain.DoesNotExist:
            pass

        return evolution_data

    def get_related_pokemon(self, pokemon, limit=6):
        """
        Get Pokemon with similar types (excluding current Pokemon)
        """
        pokemon_types = pokemon.types.all()
        if not pokemon_types:
            return Pokemon.objects.none()

        related = Pokemon.objects.filter(
            types__in=pokemon_types
        ).exclude(
            id=pokemon.id
        ).distinct().select_related().prefetch_related('types')[:limit]

        return related

    def get_stats_percentages(self, pokemon):
        """
        Calculate stat percentages for visualization (based on max stat of 255)
        """
        max_stat = 255
        return {
            'hp': (pokemon.hp / max_stat) * 100,
            'attack': (pokemon.attack / max_stat) * 100,
            'defense': (pokemon.defense / max_stat) * 100,
            'special_attack': (pokemon.special_attack / max_stat) * 100,
            'special_defense': (pokemon.special_defense / max_stat) * 100,
            'speed': (pokemon.speed / max_stat) * 100,
        }

def pokemon_search_api(request):
    """API endpoint for Pokemon search autocomplete."""
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'results': []})

    pokemon = Pokemon.objects.filter(
        Q(name__icontains=query) |
        Q(pokedex_id__icontains=query)
    )[:10]

    results = []
    for p in pokemon:
        results.append({
            'id': p.pokedex_id,
            'name': p.name.title(),
            'sprite': p.sprite_front,
            'url': reverse('pokemon:detail', kwargs={'pokedex_id': p.pokedex_id})
        })

    return JsonResponse({'results': results})


def pokemon_compare(request):
    """Pokemon comparison view."""
    pokemon1_id = request.GET.get('pokemon1')
    pokemon2_id = request.GET.get('pokemon2')

    context = {
        'pokemon1': None,
        'pokemon2': None,
        'comparison': None,
        'all_pokemon': Pokemon.objects.all().order_by('pokedex_id')
    }

    if pokemon1_id and pokemon2_id:
        try:
            comparison = PokemonDataManager.get_pokemon_stats_comparison(
                int(pokemon1_id), int(pokemon2_id)
            )
            if comparison:
                context['pokemon1'] = Pokemon.objects.get(pokedex_id=pokemon1_id)
                context['pokemon2'] = Pokemon.objects.get(pokedex_id=pokemon2_id)
                context['comparison'] = comparison
        except (ValueError, Pokemon.DoesNotExist):
            messages.error(request, "Invalid Pokemon selected for comparison.")

    return render(request, 'pokemon/pokemon_compare.html', context)


@require_http_methods(["POST"])
def toggle_favorite(request, pokedex_id):
    """Toggle Pokemon favorite status."""
    if not request.session.session_key:
        request.session.create()

    session_key = request.session.session_key
    pokemon = get_object_or_404(Pokemon, pokedex_id=pokedex_id)

    favorite, created = UserFavorite.objects.get_or_create(
        session_key=session_key,
        pokemon=pokemon
    )

    if not created:
        favorite.delete()
        is_favorite = False
        action = 'removed from'
    else:
        is_favorite = True
        action = 'added to'

    if request.headers.get('Content-Type') == 'application/json':
        return JsonResponse({
            'is_favorite': is_favorite,
            'message': f'{pokemon.name.title()} {action} favorites'
        })

    messages.success(request, f'{pokemon.name.title()} {action} favorites!')
    return redirect('pokemon:detail', pokedex_id=pokedex_id)


def favorites_list(request):
    """List user's favorite Pokemon."""
    if not request.session.session_key:
        favorites = []
    else:
        favorites = UserFavorite.objects.filter(
            session_key=request.session.session_key
        ).select_related('pokemon').order_by('-created_at')

    return render(request, 'pokemon/favorites.html', {
        'favorites': favorites
    })


def pokemon_stats_json(request, pokedex_id):
    """Return Pokemon stats as JSON for charts."""
    pokemon = get_object_or_404(Pokemon, pokedex_id=pokedex_id)

    stats_data = {
        'name': pokemon.name.title(),
        'stats': {
            'HP': pokemon.hp,
            'Attack': pokemon.attack,
            'Defense': pokemon.defense,
            'Sp. Attack': pokemon.special_attack,
            'Sp. Defense': pokemon.special_defense,
            'Speed': pokemon.speed
        },
        'total': pokemon.total_stats,
        'types': [t.name for t in pokemon.types.all()]
    }

    return JsonResponse(stats_data)


def random_pokemon(request):
    """Redirect to a random Pokemon."""
    pokemon = Pokemon.objects.order_by('?').first()
    if pokemon:
        return redirect('pokemon:detail', pokedex_id=pokemon.pokedex_id)
    else:
        messages.error(request, "No Pokemon found in database!")
        return redirect('pokemon:list')


import requests
import logging
from django.shortcuts import render, get_object_or_404
from django.http import Http404, JsonResponse
from django.core.cache import cache
from django.views.decorators.cache import cache_page
from django.utils.decorators import method_decorator
from django.views.generic import DetailView
from django.contrib import messages

logger = logging.getLogger(__name__)


class PokemonAPIClient:
    """Client for interacting with PokeAPI"""
    BASE_URL = "https://pokeapi.co/api/v2"

    @staticmethod
    def get_pokemon_data(pokemon_id_or_name):
        """Fetch Pokemon data from PokeAPI with caching"""
        cache_key = f"pokemon_{pokemon_id_or_name}"
        cached_data = cache.get(cache_key)

        if cached_data:
            return cached_data

        try:
            url = f"{PokemonAPIClient.BASE_URL}/pokemon/{pokemon_id_or_name.lower()}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()
            # Cache for 1 hour
            cache.set(cache_key, data, 3600)
            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Pokemon data for {pokemon_id_or_name}: {e}")
            return None

    @staticmethod
    def get_pokemon_species(pokemon_id):
        """Fetch Pokemon species data for evolution chain and descriptions"""
        cache_key = f"species_{pokemon_id}"
        cached_data = cache.get(cache_key)

        if cached_data:
            return cached_data

        try:
            url = f"{PokemonAPIClient.BASE_URL}/pokemon-species/{pokemon_id}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()
            cache.set(cache_key, data, 3600)
            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching species data for {pokemon_id}: {e}")
            return None

    @staticmethod
    def get_evolution_chain(chain_url):
        """Fetch evolution chain data"""
        cache_key = f"evolution_{chain_url.split('/')[-2]}"
        cached_data = cache.get(cache_key)

        if cached_data:
            return cached_data

        try:
            response = requests.get(chain_url, timeout=10)
            response.raise_for_status()

            data = response.json()
            cache.set(cache_key, data, 3600)
            return data

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching evolution chain: {e}")
            return None


# def pokemon_detail(request, pokemon_id):
#     """Display detailed information about a specific Pokemon"""
#     try:
#         # Fetch main Pokemon data
#         pokemon_data = PokemonAPIClient.get_pokemon_data(pokemon_id)
#         if not pokemon_data:
#             messages.error(request, f"Pokemon with ID/name '{pokemon_id}' not found or API unavailable.")
#             raise Http404("Pokemon not found")
#
#         # Fetch species data for additional info
#         species_data = PokemonAPIClient.get_pokemon_species(pokemon_data['id'])
#
#         # Process Pokemon data
#         context = {
#             'pokemon': process_pokemon_data(pokemon_data, species_data),
#             'stats': process_stats_data(pokemon_data.get('stats', [])),
#             'abilities': process_abilities_data(pokemon_data.get('abilities', [])),
#             'types': [type_info['type']['name'] for type_info in pokemon_data.get('types', [])],
#             'moves': process_moves_data(pokemon_data.get('moves', [])[:10]),  # Limit to first 10 moves
#         }
#
#         # Add evolution chain if available
#         if species_data and species_data.get('evolution_chain'):
#             evolution_data = PokemonAPIClient.get_evolution_chain(species_data['evolution_chain']['url'])
#             if evolution_data:
#                 context['evolution_chain'] = process_evolution_chain(evolution_data['chain'])
#
#         return render(request, 'pokemon/detail.html', context)
#
#     except Exception as e:
#         logger.error(f"Error in pokemon_detail view: {e}")
#         messages.error(request, "An error occurred while loading Pokemon data.")
#         raise Http404("Pokemon not found")


def process_pokemon_data(pokemon_data, species_data=None):
    """Process and clean Pokemon data for template"""
    processed = {
        'id': pokemon_data['id'],
        'name': pokemon_data['name'].title(),
        'height': pokemon_data['height'] / 10,  # Convert to meters
        'weight': pokemon_data['weight'] / 10,  # Convert to kg
        'base_experience': pokemon_data.get('base_experience', 0),
        'sprite_front': pokemon_data['sprites'].get('front_default'),
        'sprite_back': pokemon_data['sprites'].get('back_default'),
        'sprite_shiny_front': pokemon_data['sprites'].get('front_shiny'),
        'sprite_artwork': pokemon_data['sprites']['other']['official-artwork'].get('front_default'),
    }

    if species_data:
        # Add description (flavor text)
        flavor_texts = species_data.get('flavor_text_entries', [])
        english_texts = [entry for entry in flavor_texts if entry['language']['name'] == 'en']
        if english_texts:
            processed['description'] = english_texts[0]['flavor_text'].replace('\n', ' ').replace('\f', ' ')

        # Add generation info
        processed['generation'] = species_data.get('generation', {}).get('name', 'Unknown')
        processed['capture_rate'] = species_data.get('capture_rate', 0)
        processed['base_happiness'] = species_data.get('base_happiness', 0)

    return processed


def process_stats_data(stats):
    """Process Pokemon stats for display"""
    stat_mapping = {
        'hp': 'HP',
        'attack': 'Attack',
        'defense': 'Defense',
        'special-attack': 'Sp. Attack',
        'special-defense': 'Sp. Defense',
        'speed': 'Speed'
    }

    processed_stats = []
    total_stats = 0

    for stat in stats:
        stat_name = stat['stat']['name']
        base_stat = stat['base_stat']
        total_stats += base_stat

        processed_stats.append({
            'name': stat_mapping.get(stat_name, stat_name.title()),
            'base_stat': base_stat,
            'percentage': min(100, (base_stat / 255) * 100)  # For progress bars
        })

    return {
        'individual': processed_stats,
        'total': total_stats
    }


def process_abilities_data(abilities):
    """Process Pokemon abilities"""
    return [
        {
            'name': ability['ability']['name'].replace('-', ' ').title(),
            'is_hidden': ability['is_hidden'],
            'slot': ability['slot']
        }
        for ability in abilities
    ]


def process_moves_data(moves):
    """Process Pokemon moves (limited set)"""
    return [
        {
            'name': move['move']['name'].replace('-', ' ').title(),
            'learn_method': move['version_group_details'][0]['move_learn_method']['name'] if move[
                'version_group_details'] else 'Unknown',
            'level_learned': move['version_group_details'][0]['level_learned_at'] if move[
                'version_group_details'] else 0
        }
        for move in moves
    ]


def process_evolution_chain(chain_data):
    """Process evolution chain data"""

    def extract_evolution_info(chain):
        evolutions = []
        current = chain

        while current:
            pokemon_name = current['species']['name']
            evolutions.append({
                'name': pokemon_name.title(),
                'id': current['species']['url'].split('/')[-2],  # Extract ID from URL
            })

            # Move to next evolution (take first if multiple)
            if current.get('evolves_to'):
                current = current['evolves_to'][0]
            else:
                current = None

        return evolutions

    return extract_evolution_info(chain_data)


# API endpoint for AJAX requests
# def pokemon_detail_api(request, pokemon_id):
#     """API endpoint returning Pokemon data as JSON"""
#     pokemon_data = PokemonAPIClient.get_pokemon_data(pokemon_id)
#     if not pokemon_data:
#         return JsonResponse({'error': 'Pokemon not found'}, status=404)
#
#     species_data = PokemonAPIClient.get_pokemon_species(pokemon_data['id'])
#
#     return JsonResponse({
#         'pokemon': process_pokemon_data(pokemon_data, species_data),
#         'stats': process_stats_data(pokemon_data.get('stats', [])),
#         'abilities': process_abilities_data(pokemon_data.get('abilities', [])),
#         'types': [type_info['type']['name'] for type_info in pokemon_data.get('types', [])],
#     })
#
#
# def pokemon_compare(request):
#     """Compare two Pokemon side by side"""
#     pokemon1_id = request.GET.get('pokemon1')
#     pokemon2_id = request.GET.get('pokemon2')
#
#     if not pokemon1_id or not pokemon2_id:
#         return render(request, 'pokemon/compare.html', {
#             'error': 'Please provide two Pokemon to compare'
#         })
#
#     pokemon1_data = PokemonAPIClient.get_pokemon_data(pokemon1_id)
#     pokemon2_data = PokemonAPIClient.get_pokemon_data(pokemon2_id)
#
#     if not pokemon1_data or not pokemon2_data:
#         return render(request, 'pokemon/compare.html', {
#             'error': 'One or both Pokemon not found'
#         })
#
#     context = {
#         'pokemon1': {
#             'data': process_pokemon_data(pokemon1_data),
#             'stats': process_stats_data(pokemon1_data.get('stats', [])),
#             'types': [type_info['type']['name'] for type_info in pokemon1_data.get('types', [])],
#         },
#         'pokemon2': {
#             'data': process_pokemon_data(pokemon2_data),
#             'stats': process_stats_data(pokemon2_data.get('stats', [])),
#             'types': [type_info['type']['name'] for type_info in pokemon2_data.get('types', [])],
#         }
#     }
#
#     return render(request, 'pokemon/compare.html', context)

def pokemon_detail(request, pokedex_id):
    """Detail view for a specific Pokemon"""
    pokemon = get_object_or_404(Pokemon, pokedex_id=pokedex_id)

    # Get evolution chain
    evolution_chain = None
    if hasattr(pokemon, 'evolution_chains') and pokemon.evolution_chains.exists():
        evolution_chain = pokemon.evolution_chains.first()

    # Get evolutions from and to this Pokemon
    evolves_from = pokemon.evolves_from.all()
    evolves_to = pokemon.evolves_to.all()

    # Check if this Pokemon is favorited by current session
    session_key = request.session.session_key
    is_favorited = False
    if session_key:
        is_favorited = UserFavorite.objects.filter(
            session_key=session_key,
            pokemon=pokemon
        ).exists()

    context = {
        'pokemon': pokemon,
        'evolution_chain': evolution_chain,
        'evolves_from': evolves_from,
        'evolves_to': evolves_to,
        'is_favorited': is_favorited,
        'abilities': pokemon.ability_links.all().select_related('ability'),
        'types': pokemon.types.all(),
    }

    return render(request, 'pokemon/detail.html', context)
# def pokemon_detail(request, pokemon_id):
#     """Display detailed information about a specific Pokemon"""
#     try:
#         # Try to get Pokemon by pokedex_id first, then by name
#         if pokemon_id.isdigit():
#             pokemon = get_object_or_404(Pokemon, pokedex_id=int(pokemon_id))
#         else:
#             pokemon = get_object_or_404(Pokemon, name__iexact=pokemon_id)
#
#         # Get related data
#         abilities = pokemon.ability_links.select_related('ability').all()
#         types = pokemon.types.all()
#
#         # Get evolution chain
#         evolution_chain = []
#         try:
#             # Get evolutions where this Pokemon evolves FROM
#             evolutions_from = Evolution.objects.filter(from_pokemon=pokemon).select_related('to_pokemon')
#             # Get evolutions where this Pokemon evolves TO
#             evolutions_to = Evolution.objects.filter(to_pokemon=pokemon).select_related('from_pokemon')
#
#             # Build a simple evolution chain
#             for evo in evolutions_to:
#                 evolution_chain.append({
#                     'pokemon': evo.from_pokemon,
#                     'direction': 'from'
#                 })
#
#             evolution_chain.append({
#                 'pokemon': pokemon,
#                 'direction': 'current'
#             })
#
#             for evo in evolutions_from:
#                 evolution_chain.append({
#                     'pokemon': evo.to_pokemon,
#                     'direction': 'to'
#                 })
#
#         except Exception as e:
#             logger.warning(f"Could not load evolution chain for {pokemon.name}: {e}")
#
#         # Process stats for display
#         stats = [
#             {'name': 'HP', 'value': pokemon.hp, 'percentage': (pokemon.hp / 255) * 100},
#             {'name': 'Attack', 'value': pokemon.attack, 'percentage': (pokemon.attack / 255) * 100},
#             {'name': 'Defense', 'value': pokemon.defense, 'percentage': (pokemon.defense / 255) * 100},
#             {'name': 'Sp. Attack', 'value': pokemon.special_attack, 'percentage': (pokemon.special_attack / 255) * 100},
#             {'name': 'Sp. Defense', 'value': pokemon.special_defense,
#              'percentage': (pokemon.special_defense / 255) * 100},
#             {'name': 'Speed', 'value': pokemon.speed, 'percentage': (pokemon.speed / 255) * 100},
#         ]
#
#         # Check if this Pokemon is in user's favorites
#         session_key = request.session.session_key
#         if not session_key:
#             request.session.create()
#             session_key = request.session.session_key
#
#         is_favorite = UserFavorite.objects.filter(
#             session_key=session_key,
#             pokemon=pokemon
#         ).exists()
#
#         # Get next and previous Pokemon for navigation
#         next_pokemon = Pokemon.objects.filter(pokedex_id__gt=pokemon.pokedex_id).first()
#         prev_pokemon = Pokemon.objects.filter(pokedex_id__lt=pokemon.pokedex_id).last()
#
#         context = {
#             'pokemon': pokemon,
#             'abilities': abilities,
#             'types': types,
#             'stats': stats,
#             'total_stats': pokemon.total_stats,
#             'evolution_chain': evolution_chain,
#             'is_favorite': is_favorite,
#             'next_pokemon': next_pokemon,
#             'prev_pokemon': prev_pokemon,
#         }
#
#         return render(request, 'pokemon/detail.html', context)
#
#     except Pokemon.DoesNotExist:
#         messages.error(request, f"Pokemon '{pokemon_id}' not found in database.")
#         return render(request, 'pokemon/not_found.html', {'pokemon_id': pokemon_id})
#     except Exception as e:
#         logger.error(f"Error in pokemon_detail view: {e}")
#         messages.error(request, "An error occurred while loading Pokemon data.")
#         raise Http404("Pokemon not found")


def pokemon_list(request):
    """Display list of all Pokemon with search and filtering"""
    pokemon_list = Pokemon.objects.select_related().prefetch_related('types', 'ability_links__ability')

    # Search functionality
    search_query = request.GET.get('search', '').strip()
    if search_query:
        pokemon_list = pokemon_list.filter(
            Q(name__icontains=search_query) |
            Q(pokedex_id__exact=search_query if search_query.isdigit() else None)
        )

    # Type filtering
    type_filter = request.GET.get('type')
    if type_filter:
        pokemon_list = pokemon_list.filter(types__name__iexact=type_filter)

    # Sorting
    sort_by = request.GET.get('sort', 'pokedex_id')
    if sort_by in ['name', 'pokedex_id', 'total_stats', 'hp', 'attack', 'defense', 'speed']:
        if sort_by == 'total_stats':
            # Can't sort by property, so we'll sort by ID for now
            sort_by = 'pokedex_id'
        pokemon_list = pokemon_list.order_by(sort_by)

    # Pagination
    paginator = Paginator(pokemon_list, 20)  # Show 20 Pokemon per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Get all types for filter dropdown
    all_types = PokemonType.objects.all().order_by('name')

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'type_filter': type_filter,
        'sort_by': sort_by,
        'all_types': all_types,
        'total_count': pokemon_list.count(),
    }

    return render(request, 'pokemon/list.html', context)


# def pokemon_compare(request):
#     """Compare two Pokemon side by side"""
#     pokemon1_id = request.GET.get('pokemon1')
#     pokemon2_id = request.GET.get('pokemon2')
#
#     if not pokemon1_id or not pokemon2_id:
#         # Show comparison form
#         all_pokemon = Pokemon.objects.all().order_by('pokedex_id')
#         return render(request, 'pokemon/compare.html', {
#             'all_pokemon': all_pokemon,
#             'show_form': True
#         })
#
#     try:
#         if pokemon1_id.isdigit():
#             pokemon1 = get_object_or_404(Pokemon, pokedex_id=int(pokemon1_id))
#         else:
#             pokemon1 = get_object_or_404(Pokemon, name__iexact=pokemon1_id)
#
#         if pokemon2_id.isdigit():
#             pokemon2 = get_object_or_404(Pokemon, pokedex_id=int(pokemon2_id))
#         else:
#             pokemon2 = get_object_or_404(Pokemon, name__iexact=pokemon2_id)
#
#         # Prepare comparison data
#         comparison_data = {
#             'pokemon1': {
#                 'pokemon': pokemon1,
#                 'types': pokemon1.types.all(),
#                 'abilities': pokemon1.ability_links.select_related('ability').all(),
#                 'stats': [
#                     {'name': 'HP', 'value': pokemon1.hp},
#                     {'name': 'Attack', 'value': pokemon1.attack},
#                     {'name': 'Defense', 'value': pokemon1.defense},
#                     {'name': 'Sp. Attack', 'value': pokemon1.special_attack},
#                     {'name': 'Sp. Defense', 'value': pokemon1.special_defense},
#                     {'name': 'Speed', 'value': pokemon1.speed},
#                 ]
#             },
#             'pokemon2': {
#                 'pokemon': pokemon2,
#                 'types': pokemon2.types.all(),
#                 'abilities': pokemon2.ability_links.select_related('ability').all(),
#                 'stats': [
#                     {'name': 'HP', 'value': pokemon2.hp},
#                     {'name': 'Attack', 'value': pokemon2.attack},
#                     {'name': 'Defense', 'value': pokemon2.defense},
#                     {'name': 'Sp. Attack', 'value': pokemon2.special_attack},
#                     {'name': 'Sp. Defense', 'value': pokemon2.special_defense},
#                     {'name': 'Speed', 'value': pokemon2.speed},
#                 ]
#             }
#         }
#
#         # Calculate stat differences
#         stat_comparison = []
#         for i, stat in enumerate(comparison_data['pokemon1']['stats']):
#             stat1_val = stat['value']
#             stat2_val = comparison_data['pokemon2']['stats'][i]['value']
#             stat_comparison.append({
#                 'name': stat['name'],
#                 'pokemon1': stat1_val,
#                 'pokemon2': stat2_val,
#                 'difference': stat1_val - stat2_val,
#                 'winner': 1 if stat1_val > stat2_val else 2 if stat2_val > stat1_val else 0
#             })
#
#         comparison_data['stat_comparison'] = stat_comparison
#         comparison_data['total_stats'] = {
#             'pokemon1': pokemon1.total_stats,
#             'pokemon2': pokemon2.total_stats,
#         }
#
#         return render(request, 'pokemon/compare.html', comparison_data)
#
#     except Pokemon.DoesNotExist:
#         messages.error(request, "One or both Pokemon not found.")
#         return render(request, 'pokemon/compare.html', {'error': 'Pokemon not found'})


def pokemon_random(request):
    """Redirect to a random Pokemon"""
    from django.shortcuts import redirect

    # Get a random Pokemon
    pokemon_count = Pokemon.objects.count()
    if pokemon_count == 0:
        messages.error(request, "No Pokemon found in database.")
        return redirect('pokemon:list')

    random_offset = random.randint(0, pokemon_count - 1)
    random_pokemon = Pokemon.objects.all()[random_offset]

    return redirect('pokemon:detail', pokemon_id=random_pokemon.pokedex_id)


def pokemon_by_type(request, type_name):
    """Show all Pokemon of a specific type"""
    try:
        pokemon_type = get_object_or_404(PokemonType, name__iexact=type_name)
        pokemon_list = Pokemon.objects.filter(types=pokemon_type).order_by('pokedex_id')

        # Pagination
        paginator = Paginator(pokemon_list, 20)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        context = {
            'pokemon_type': pokemon_type,
            'page_obj': page_obj,
            'total_count': pokemon_list.count(),
        }

        return render(request, 'pokemon/by_type.html', context)

    except PokemonType.DoesNotExist:
        messages.error(request, f"Pokemon type '{type_name}' not found.")
        return redirect('pokemon:list')


def pokemon_search(request):
    """Advanced search functionality"""
    query = request.GET.get('q', '').strip()
    type_filter = request.GET.get('type', '')
    min_stats = request.GET.get('min_stats', '')
    legendary_filter = request.GET.get('legendary', '')

    pokemon_list = Pokemon.objects.all()

    if query:
        pokemon_list = pokemon_list.filter(
            Q(name__icontains=query) |
            Q(pokedex_id__exact=query if query.isdigit() else None)
        )

    if type_filter:
        pokemon_list = pokemon_list.filter(types__name__iexact=type_filter)

    if min_stats and min_stats.isdigit():
        # Filter by minimum total stats
        min_total = int(min_stats)
        # This is a simplified filter - in a real app you'd want to add a computed field
        pokemon_list = [p for p in pokemon_list if p.total_stats >= min_total]

    if legendary_filter == 'true':
        pokemon_list = pokemon_list.filter(is_legendary=True)
    elif legendary_filter == 'false':
        pokemon_list = pokemon_list.filter(is_legendary=False)

    # If we used list comprehension, convert back to queryset behavior
    if isinstance(pokemon_list, list):
        total_count = len(pokemon_list)
        # Simple pagination for list
        page_size = 20
        page_num = int(request.GET.get('page', 1))
        start_idx = (page_num - 1) * page_size
        end_idx = start_idx + page_size
        pokemon_list = pokemon_list[start_idx:end_idx]
    else:
        total_count = pokemon_list.count()
        # Standard pagination
        paginator = Paginator(pokemon_list, 20)
        page_number = request.GET.get('page')
        pokemon_list = paginator.get_page(page_number)

    # Get all types for filter
    all_types = PokemonType.objects.all().order_by('name')

    context = {
        'pokemon_list': pokemon_list,
        'query': query,
        'type_filter': type_filter,
        'min_stats': min_stats,
        'legendary_filter': legendary_filter,
        'all_types': all_types,
        'total_count': total_count,
    }

    return render(request, 'pokemon/search.html', context)


def toggle_favorite(request, pokemon_id):
    """Toggle Pokemon favorite status"""
    if request.method == 'POST':
        try:
            pokemon = get_object_or_404(Pokemon, pokedex_id=pokemon_id)

            # Ensure session exists
            if not request.session.session_key:
                request.session.create()

            session_key = request.session.session_key

            favorite, created = UserFavorite.objects.get_or_create(
                session_key=session_key,
                pokemon=pokemon
            )

            if not created:
                favorite.delete()
                is_favorite = False
            else:
                is_favorite = True

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'is_favorite': is_favorite})
            else:
                return redirect('pokemon:detail', pokemon_id=pokemon_id)

        except Exception as e:
            logger.error(f"Error toggling favorite: {e}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Failed to toggle favorite'}, status=500)
            else:
                messages.error(request, "Failed to update favorite status.")
                return redirect('pokemon:detail', pokemon_id=pokemon_id)

    return redirect('pokemon:list')


def user_favorites(request):
    """Show user's favorite Pokemon"""
    session_key = request.session.session_key
    if not session_key:
        favorites = []
    else:
        favorites = UserFavorite.objects.filter(
            session_key=session_key
        ).select_related('pokemon').order_by('-created_at')

    context = {
        'favorites': favorites,
        'total_count': len(favorites),
    }

    return render(request, 'pokemon/favorites.html', context)


# API endpoints
def pokemon_detail_api(request, pokemon_id):
    """API endpoint returning Pokemon data as JSON"""
    try:
        if pokemon_id.isdigit():
            pokemon = get_object_or_404(Pokemon, pokedex_id=int(pokemon_id))
        else:
            pokemon = get_object_or_404(Pokemon, name__iexact=pokemon_id)

        data = {
            'id': pokemon.pokedex_id,
            'name': pokemon.name,
            'height': pokemon.height_meters,
            'weight': pokemon.weight_kg,
            'base_experience': pokemon.base_experience,
            'is_legendary': pokemon.is_legendary,
            'is_mythical': pokemon.is_mythical,
            'sprites': {
                'front': pokemon.sprite_front,
                'back': pokemon.sprite_back,
                'artwork': pokemon.official_artwork,
            },
            'stats': {
                'hp': pokemon.hp,
                'attack': pokemon.attack,
                'defense': pokemon.defense,
                'special_attack': pokemon.special_attack,
                'special_defense': pokemon.special_defense,
                'speed': pokemon.speed,
                'total': pokemon.total_stats,
            },
            'types': [t.name for t in pokemon.types.all()],
            'abilities': [
                {
                    'name': link.ability.name,
                    'is_hidden': link.is_hidden,
                    'slot': link.slot,
                }
                for link in pokemon.ability_links.select_related('ability').all()
            ],
        }

        return JsonResponse(data)

    except Pokemon.DoesNotExist:
        return JsonResponse({'error': 'Pokemon not found'}, status=404)