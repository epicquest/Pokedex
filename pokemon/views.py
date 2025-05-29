from django.http import HttpResponse
from django.shortcuts import render

# pokemon/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, Http404
from django.views.generic import ListView, DetailView
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator
from django.urls import reverse
import json

from .models import Pokemon, PokemonType, UserFavorite
from .services import PokemonDataManager, PokeAPIService


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


class PokemonDetailView(DetailView):
    model = Pokemon
    template_name = 'pokemon/pokemon_detail.html'
    context_object_name = 'pokemon'
    slug_field = 'pokedex_id'
    slug_url_kwarg = 'pokedex_id'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pokemon = self.get_object()

        # Get evolution data (simplified - you might want to implement proper evolution chains)
        context['evolutions'] = Pokemon.objects.filter(
            pokedex_id__in=[pokemon.pokedex_id - 1, pokemon.pokedex_id + 1]
        ).exclude(pokedex_id=pokemon.pokedex_id)

        # Check if this Pokemon is in favorites
        session_key = self.request.session.session_key
        if session_key:
            context['is_favorite'] = UserFavorite.objects.filter(
                session_key=session_key,
                pokemon=pokemon
            ).exists()
        else:
            context['is_favorite'] = False

        # Get related Pokemon (same type)
        context['related_pokemon'] = Pokemon.objects.filter(
            types__in=pokemon.types.all()
        ).exclude(id=pokemon.id).distinct()[:6]

        return context


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

def home(request):
    return HttpResponse("Hello, Django!")