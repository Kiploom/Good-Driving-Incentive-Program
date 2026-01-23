from app import create_app
import sys
import logging

# Configure logging BEFORE creating the app to ensure all logs are captured
# This sets up the root logger and werkzeug logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)  # Explicitly use stdout
    ]
)

# Set werkzeug logger to INFO level (it defaults to WARNING)
logging.getLogger('werkzeug').setLevel(logging.INFO)

app = create_app()

# Ensure Flask app logger is set to INFO and has a handler
app.logger.setLevel(logging.INFO)
# Remove any existing handlers to avoid duplicates
app.logger.handlers = []
# Add a stream handler to ensure logs go to stdout
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
app.logger.addHandler(handler)

if __name__ == '__main__':
    # Note: Auto-reloader disabled to avoid Windows WinError 10038
    # You'll need to manually restart the server when you make code changes
    
    try:
        app.run(
            host='0.0.0.0', 
            port=5000, 
            debug=True, 
            use_reloader=False  # Disabled to prevent Windows socket errors
        )
    except (KeyboardInterrupt, SystemExit):
        # Clean shutdown on Ctrl+C
        print("\nShutting down gracefully...")
        sys.exit(0)