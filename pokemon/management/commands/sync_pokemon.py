
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from pokemon.services import PokemonDataManager, PokeAPIService
import time


class Command(BaseCommand):
    help = 'Sync Pokemon data from PokeAPI'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=151,
            help='Number of Pokemon to sync (default: 151 for Gen 1)'
        )
        parser.add_argument(
            '--offset',
            type=int,
            default=0,
            help='Starting offset for Pokemon sync'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=20,
            help='Number of Pokemon to process in each batch'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=0.1,
            help='Delay between requests to avoid rate limiting (seconds)'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        offset = options['offset']
        batch_size = options['batch_size']
        delay = options['delay']

        self.stdout.write(
            self.style.SUCCESS(f'Starting Pokemon sync: {limit} Pokemon from offset {offset}')
        )

        # Sync types first
        self.stdout.write('Syncing Pokemon types...')
        PokemonDataManager.sync_pokemon_types()
        self.stdout.write(self.style.SUCCESS('Pokemon types synced successfully'))

        # Sync Pokemon in batches
        total_synced = 0
        current_offset = offset

        while total_synced < limit:
            current_batch_size = min(batch_size, limit - total_synced)

            self.stdout.write(
                f'Syncing batch: {current_offset + 1} to {current_offset + current_batch_size}'
            )

            try:
                with transaction.atomic():
                    synced_pokemon = PokemonDataManager.sync_pokemon_batch(
                        limit=current_batch_size,
                        offset=current_offset
                    )

                    if synced_pokemon:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'Successfully synced {len(synced_pokemon)} Pokemon'
                            )
                        )
                        total_synced += len(synced_pokemon)
                    else:
                        self.stdout.write(
                            self.style.WARNING('No Pokemon synced in this batch')
                        )
                        break

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Error syncing batch: {e}')
                )
                break

            current_offset += current_batch_size

            # Add delay to avoid rate limiting
            if delay > 0:
                time.sleep(delay)

        self.stdout.write(
            self.style.SUCCESS(f'Pokemon sync completed! Total synced: {total_synced}')
        )