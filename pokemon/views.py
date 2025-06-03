import random

import requests
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.core.cache import cache
from django.contrib import messages

from django.core.paginator import Paginator
from django.shortcuts import redirect

from django.views.generic import ListView, DetailView
from django.views.decorators.http import require_http_methods, require_POST
from django.db.models import Q
from django.urls import reverse

from .models import Pokemon, PokemonType, UserFavorite, Evolution, EvolutionChain
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
        session_key = self.request.session.session_key
        if not session_key:
            self.request.session.save()
            session_key = self.request.session.session_key

        favorite_ids = set(
            UserFavorite.objects.filter(session_key=session_key)
            .values_list('pokemon_id', flat=True)
        )

        context['favorite_ids'] = favorite_ids
        context['pokemon_types'] = PokemonType.objects.all().order_by('name')
        context['current_search'] = self.request.GET.get('search', '')
        context['current_type'] = self.request.GET.get('type', '')
        context['current_generation'] = self.request.GET.get('generation', '')
        context['current_sort'] = self.request.GET.get('sort', 'pokedex_id')
        context['is_reverse'] = self.request.GET.get('reverse') == 'true'

        return context


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
            'url': reverse('pokemon:detail', kwargs={'pk': p.pokedex_id})
        })

    return JsonResponse({'results': results})


@require_http_methods(["POST"])
def toggle_favorite(request, pokedex_id):
    """Toggle Pokemon favorite status."""
    if not request.session.session_key:
        request.session.create()

    session_key = request.session.session_key
    try:
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
    except Exception as e:
             return JsonResponse({
                 'success': False,
                 'error': str(e)
             }, status=400)
    return redirect('pokemon:detail', pk=pokedex_id)


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
        return redirect('pokemon:detail', pk=pokemon.pokedex_id)
    else:
        messages.error(request, "No Pokemon found in database!")
        return redirect('pokemon:list')




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

    return redirect('pokemon:detail', pk=random_pokemon.pokedex_id)


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



def favorites_view(request):
    """Display user's favorite Pokemon"""
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key

    # Get user's favorite Pokemon
    favorite_objects = UserFavorite.objects.filter(session_key=session_key).select_related('pokemon')
    favorite_pokemon = [fav.pokemon for fav in favorite_objects]

    # Add stats percentage to each Pokemon (max possible stats is around 720)
    for pokemon in favorite_pokemon:
        pokemon.stats_percentage = min(round((pokemon.total_stats / 720) * 100, 1), 100)

    # Handle sorting
    sort_param = request.GET.get('sort', 'pokedex_id')

    if sort_param == 'date_added':
        # Sort by when they were added to favorites (most recent first)
        favorite_objects = favorite_objects.order_by('-created_at')
        favorite_pokemon = [fav.pokemon for fav in favorite_objects]
    elif sort_param == 'total_stats':
        # Sort by total stats (highest first)
        favorite_pokemon = sorted(favorite_pokemon, key=lambda p: p.total_stats, reverse=True)
    elif sort_param in ['pokedex_id', 'name', 'hp', 'attack', 'defense', 'speed']:
        # Sort by Pokemon attributes
        reverse = sort_param not in ['pokedex_id', 'name']  # Numeric stats should be descending
        favorite_pokemon = sorted(favorite_pokemon, key=lambda p: getattr(p, sort_param), reverse=reverse)

    # Calculate statistics
    stats = {}
    if favorite_pokemon:
        # Type distribution with colors
        type_info = {}
        for pokemon in favorite_pokemon:
            for ptype in pokemon.types.all():
                if ptype.name not in type_info:
                    type_info[ptype.name] = {'count': 0, 'color': ptype.color}
                type_info[ptype.name]['count'] += 1

        stats['type_distribution'] = type_info

        # Average stats
        total_stats = [pokemon.total_stats for pokemon in favorite_pokemon]
        stats['average_stats'] = sum(total_stats) / len(total_stats) if total_stats else 0

        # Strongest Pokemon
        stats['strongest_pokemon'] = max(favorite_pokemon, key=lambda p: p.total_stats)

    context = {
        'favorite_pokemon': favorite_pokemon,
        'current_sort': sort_param,
        'type_distribution': stats.get('type_distribution', {}),
        'average_stats': stats.get('average_stats', 0),
        'strongest_pokemon': stats.get('strongest_pokemon'),
    }

    return render(request, 'pokemon/favorites.html', context)

@require_POST
def clear_favorites(request):

    """Clear all favorites for the current session"""
    session_key = request.session.session_key
    if not session_key:
        return JsonResponse({'success': True, 'message': 'No favorites to clear'})

    try:
        deleted_count = UserFavorite.objects.filter(session_key=session_key).delete()[0]
        return JsonResponse({
            'success': True,
            'message': f'Cleared {deleted_count} favorites',
            'count': deleted_count
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)


def get_favorite_ids(request):
    """Helper function to get favorite Pokemon IDs for current session"""
    session_key = request.session.session_key
    if not session_key:
        return []

    return list(UserFavorite.objects.filter(
        session_key=session_key
    ).values_list('pokemon_id', flat=True))