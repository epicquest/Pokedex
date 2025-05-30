from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
import json


class PokemonType(models.Model):
    name = models.CharField(max_length=50, unique=True)
    color = models.CharField(max_length=7, default='#000000')  # Hex color for UI

    def __str__(self):
        return self.name.title()


class Pokemon(models.Model):
    # Basic info
    pokedex_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=100)
    height = models.IntegerField()  # in decimeters
    weight = models.IntegerField()  # in hectograms

    # Images
    sprite_front = models.URLField(blank=True, null=True)
    sprite_back = models.URLField(blank=True, null=True)
    official_artwork = models.URLField(blank=True, null=True)

    # Stats
    hp = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(255)])
    attack = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(255)])
    defense = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(255)])
    special_attack = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(255)])
    special_defense = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(255)])
    speed = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(255)])

    # Relationships
    types = models.ManyToManyField(PokemonType, related_name='pokemon')

    # Metadata
    base_experience = models.IntegerField(default=0)
    is_legendary = models.BooleanField(default=False)
    is_mythical = models.BooleanField(default=False)

    # API data cache
    api_data_cached_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['pokedex_id']

    def __str__(self):
        return f"#{self.pokedex_id:03d} {self.name.title()}"

    @property
    def total_stats(self):
        return self.hp + self.attack + self.defense + self.special_attack + self.special_defense + self.speed

    @property
    def height_meters(self):
        return self.height / 10  # Convert decimeters to meters

    @property
    def weight_kg(self):
        return self.weight / 10  # Convert hectograms to kg


class PokemonAbility(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_hidden = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = "Pokemon Abilities"

    def __str__(self):
        return self.name.title()


class PokemonAbilityLink(models.Model):
    pokemon = models.ForeignKey(Pokemon, on_delete=models.CASCADE, related_name='ability_links')
    ability = models.ForeignKey(PokemonAbility, on_delete=models.CASCADE)
    is_hidden = models.BooleanField(default=False)
    slot = models.IntegerField(default=1)

    class Meta:
        unique_together = ['pokemon', 'ability']


class EvolutionChain(models.Model):
    chain_id = models.IntegerField(unique=True)
    base_pokemon = models.ForeignKey(Pokemon, on_delete=models.CASCADE, related_name='evolution_chains')

    def __str__(self):
        return f"Evolution Chain {self.chain_id}"


class Evolution(models.Model):
    chain = models.ForeignKey(EvolutionChain, on_delete=models.CASCADE, related_name='evolutions')
    from_pokemon = models.ForeignKey(Pokemon, on_delete=models.CASCADE, related_name='evolves_from')
    to_pokemon = models.ForeignKey(Pokemon, on_delete=models.CASCADE, related_name='evolves_to')
    trigger = models.CharField(max_length=50)  # level-up, trade, etc.
    min_level = models.IntegerField(null=True, blank=True)
    item = models.CharField(max_length=100, blank=True)
    condition = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"{self.from_pokemon.name} → {self.to_pokemon.name}"


class UserFavorite(models.Model):
    session_key = models.CharField(max_length=40)
    pokemon = models.ForeignKey(Pokemon, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['session_key', 'pokemon']
