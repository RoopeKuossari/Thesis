"""
CLI tool for managing user accounts.

Usage
-----
Create a user (password is prompted securely if omitted):
    python -m backend.create_user create --username alice
    python -m backend.create_user create --username alice --password "s3cr3t"

Delete a user:
    python -m backend.create_user delete --username alice

List all users:
    python -m backend.create_user list
"""
import argparse
import getpass
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog='python -m backend.create_user',
        description='Manage face-recognition system user accounts.',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # create
    p_create = sub.add_parser('create', help='Create a new user account.')
    p_create.add_argument('--username', required=True, help='Login username.')
    p_create.add_argument(
        '--password',
        default=None,
        help='Password (8+ chars). Prompted securely if omitted.',
    )

    # delete
    p_delete = sub.add_parser('delete', help='Delete a user account.')
    p_delete.add_argument('--username', required=True, help='Username to remove.')

    # list
    sub.add_parser('list', help='List all registered usernames.')

    args = parser.parse_args()

    # Import here so the module can be parsed without heavy deps loaded
    from backend.auth import AuthDB
    db = AuthDB()

    # ------------------------------------------------------------------ create
    if args.command == 'create':
        password = args.password
        if password is None:
            password = getpass.getpass('Password: ')
            confirm  = getpass.getpass('Confirm password: ')
            if password != confirm:
                print('Error: passwords do not match.')
                sys.exit(1)

        if len(password) < 8:
            print('Error: password must be at least 8 characters.')
            sys.exit(1)

        if db.create_user(args.username, password):
            print(f'User "{args.username}" created successfully.')
        else:
            print(f'Error: username "{args.username}" is already taken.')
            sys.exit(1)

    # ------------------------------------------------------------------ delete
    elif args.command == 'delete':
        confirm = input(f'Delete user "{args.username}"? [y/N] ').strip().lower()
        if confirm != 'y':
            print('Aborted.')
            sys.exit(0)

        if db.delete_user(args.username):
            print(f'User "{args.username}" deleted.')
        else:
            print(f'Error: user "{args.username}" not found.')
            sys.exit(1)

    # ------------------------------------------------------------------ list
    elif args.command == 'list':
        users = db.list_users()
        if users:
            print(f'{len(users)} user(s):')
            for u in users:
                print(f'  {u}')
        else:
            print('No users registered. Create one with:')
            print('  python -m backend.create_user create --username <name>')


if __name__ == '__main__':
    main()
