# Frontend

This project was generated using [Angular CLI](https://github.com/angular/angular-cli) version 19.2.27.

## Development server

The app calls the backend through the dev proxy in `proxy.conf.json`, which forwards `/api` to
`http://127.0.0.1:8000`. Start the backend first, in another terminal:

```bash
cd backend
pip install -r requirements-dev.txt   # first time only
alembic upgrade head                   # first time, and after pulling new migrations
python -m app.cli create-admin --email you@example.com --name "Your Name" --mobile 98XXXXXXXX   # first time only
SMS_PROVIDER=console uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

With `SMS_PROVIDER=console`, sign-in codes are printed in that backend terminal instead of being texted.
If the proxy logs `ECONNREFUSED`, the backend is not running on port 8000.

Then start the frontend:

```bash
ng serve
```

Once the server is running, open your browser and navigate to `http://localhost:4200/`. The application will automatically reload whenever you modify any of the source files.

## Code scaffolding

Angular CLI includes powerful code scaffolding tools. To generate a new component, run:

```bash
ng generate component component-name
```

For a complete list of available schematics (such as `components`, `directives`, or `pipes`), run:

```bash
ng generate --help
```

## Building

To build the project run:

```bash
ng build
```

This will compile your project and store the build artifacts in the `dist/` directory. By default, the production build optimizes your application for performance and speed.

## Running unit tests

To execute unit tests with the [Karma](https://karma-runner.github.io) test runner, use the following command:

```bash
ng test
```

## Running end-to-end tests

For end-to-end (e2e) testing, run:

```bash
ng e2e
```

Angular CLI does not come with an end-to-end testing framework by default. You can choose one that suits your needs.

## Additional Resources

For more information on using the Angular CLI, including detailed command references, visit the [Angular CLI Overview and Command Reference](https://angular.dev/tools/cli) page.
