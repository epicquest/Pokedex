# Generated by Django 5.2.1 on 2025-05-29 14:56

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Pokemon',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pokedex_id', models.IntegerField(unique=True)),
                ('name', models.CharField(max_length=100)),
                ('height', models.IntegerField()),
                ('weight', models.IntegerField()),
                ('sprite_front', models.URLField(blank=True, null=True)),
                ('sprite_back', models.URLField(blank=True, null=True)),
                ('official_artwork', models.URLField(blank=True, null=True)),
                ('hp', models.IntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(255)])),
                ('attack', models.IntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(255)])),
                ('defense', models.IntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(255)])),
                ('special_attack', models.IntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(255)])),
                ('special_defense', models.IntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(255)])),
                ('speed', models.IntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(255)])),
                ('base_experience', models.IntegerField(default=0)),
                ('is_legendary', models.BooleanField(default=False)),
                ('is_mythical', models.BooleanField(default=False)),
                ('api_data_cached_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'ordering': ['pokedex_id'],
            },
        ),
        migrations.CreateModel(
            name='PokemonAbility',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('description', models.TextField(blank=True)),
                ('is_hidden', models.BooleanField(default=False)),
            ],
            options={
                'verbose_name_plural': 'Pokemon Abilities',
            },
        ),
        migrations.CreateModel(
            name='PokemonType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, unique=True)),
                ('color', models.CharField(default='#000000', max_length=7)),
            ],
        ),
        migrations.CreateModel(
            name='EvolutionChain',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chain_id', models.IntegerField(unique=True)),
                ('base_pokemon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='evolution_chains', to='pokemon.pokemon')),
            ],
        ),
        migrations.CreateModel(
            name='Evolution',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('trigger', models.CharField(max_length=50)),
                ('min_level', models.IntegerField(blank=True, null=True)),
                ('item', models.CharField(blank=True, max_length=100)),
                ('condition', models.CharField(blank=True, max_length=200)),
                ('chain', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='evolutions', to='pokemon.evolutionchain')),
                ('from_pokemon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='evolves_from', to='pokemon.pokemon')),
                ('to_pokemon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='evolves_to', to='pokemon.pokemon')),
            ],
        ),
        migrations.AddField(
            model_name='pokemon',
            name='types',
            field=models.ManyToManyField(related_name='pokemon', to='pokemon.pokemontype'),
        ),
        migrations.CreateModel(
            name='PokemonAbilityLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_hidden', models.BooleanField(default=False)),
                ('slot', models.IntegerField(default=1)),
                ('ability', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pokemon.pokemonability')),
                ('pokemon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ability_links', to='pokemon.pokemon')),
            ],
            options={
                'unique_together': {('pokemon', 'ability')},
            },
        ),
        migrations.CreateModel(
            name='UserFavorite',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('session_key', models.CharField(max_length=40)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('pokemon', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='pokemon.pokemon')),
            ],
            options={
                'unique_together': {('session_key', 'pokemon')},
            },
        ),
    ]
