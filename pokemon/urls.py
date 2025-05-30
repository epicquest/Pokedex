from django.urls import path
from . import views

app_name = 'pokemon'

urlpatterns = [
    path('', views.PokemonListView.as_view(), name='list'),
    path('pokemon/<str:pk>/', views.PokemonDetailView.as_view(), name='detail'),

    path('random/', views.random_pokemon, name='random'),

    # API endpoints
    path('api/search/', views.pokemon_search_api, name='search_api'),
    path('api/pokemon/<int:pokedex_id>/stats/', views.pokemon_stats_json, name='stats_api'),

    # Actions
    path('pokemon/<int:pokedex_id>/favorite/', views.toggle_favorite, name='toggle_favorite'),

    # Favorites URLs
    path('favorites/', views.favorites_view, name='favorites'),
    path('toggle-favorite/<int:pokemon_id>/', views.toggle_favorite, name='toggle_favorite'),
    path('clear-favorites/', views.clear_favorites, name='clear_favorites'),
]