# Import necessary libraries
from dotenv import load_dotenv
import os
import spotipy
import time
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, request, url_for, session, redirect
import googleapiclient.discovery

# Initialize Flask app and load environment variables
app = Flask(__name__)

load_dotenv()
app.config['SESSION_COOKIE_NAME'] = 'spotify-login-session'
app.config['REDIRECT_URI'] = os.getenv("SPOTIPY_REDIRECT_URI")
app.secret_key = os.getenv("SPOTIPY_CLIENT_SECRET")
TOKEN_INFO = 'token_info'
yt_apikey = os.getenv("YT_API_KEY")

# Route for Spotify login
@app.route('/')
def login():
    auth_url = create_spotify_oauth().get_authorize_url()
    return redirect(auth_url)

# Route to handle redirect from Spotify
@app.route('/redirect')
def redirect_page():
    spotify_oauth = create_spotify_oauth()
    response_url = request.url
    error = request.args.get('error')
    if error:
        return f"Auth error: {error}"

    code = request.args.get('code')
    if not code:
        return 'No code provided in redirect URL'

    token_info = spotify_oauth.get_access_token(code, as_dict=True)
    session[TOKEN_INFO] = token_info
    return redirect(url_for('youtube_auth'))

# Route to authenticate with YouTube and fetch playlist data
@app.route('/youtube_auth')
def youtube_auth():
    api_service_name = "youtube"
    api_version = "v3"
    youtube = googleapiclient.discovery.build(
    api_service_name, api_version, developerKey=yt_apikey)

    # YouTube channel handle
    handle = "exampleChannelHandle"  # Replace with actual channel handle

    response = youtube.channels().list(
        part="snippet,contentDetails, statistics, id",
        forHandle=handle
    ).execute()
    channel_id = response["items"][0]["id"]

    # Fetch playlists and find "forSpotify" playlist
    playlist_id = None
    response = youtube.playlists().list(
        part="id,snippet,contentDetails",
        channelId=channel_id,
        maxResults=50,
    ).execute()

    for pl in response["items"]:
        if pl["snippet"]["title"] == "forSpotify":
            playlist_id = pl["id"]
            break
        if not playlist_id:
            return "No forSpotify playlist found"
    
    # Fetch videos from the "forSpotify" playlist
    response = youtube.playlistItems().list(
        part="snippet",
        playlistId=playlist_id,
        maxResults=50,
    ).execute()
    
    videos = []

    for video in response["items"]:
        videos.append(
            video["snippet"]["title"]
        )
    
    # Clean video titles
    ch = ['(', '|', '[']
    for idx, vid in enumerate(videos):
        for i in range(len(vid)):
            if vid[i] in ch:
                videos[idx] = vid[:i]
                break
    
    session['yt_videos'] = videos
    return redirect(url_for('save_from_youtube'))

# Route to save tracks from YouTube playlist to Spotify
@app.route('/save_from_youtube')
def save_from_youtube():
    try:
        token_info = get_token()
    except Exception as e:
        print(f"Token error: {e}")
        return redirect('/login')
    
    sp = spotipy.Spotify(auth=token_info['access_token'])
    user_id = sp.current_user()['id']
    current_playlists = sp.current_user_playlists()['items']
    fromYoutube_playlist_id = None
    yt_videos = session.get('yt_videos', [])

    # Search for each YouTube video title on Spotify and collect URIs
    song_uris = []
    for video_title in yt_videos:
        results = sp.search(q=video_title, type='track', limit=1)
        tracks = results.get('tracks', {}).get('items', [])
        if tracks:
            song_uris.append(tracks[0]['uri'])

    # Check if "fromYoutube" playlist exists and update or create it
    for playlist in current_playlists:
        if playlist['name'] == "fromYoutube":
            fromYoutube_playlist_id = playlist['id']
            break

    if fromYoutube_playlist_id:
        existing_uris = []
        results = sp.playlist_tracks(fromYoutube_playlist_id)

        for item in results['items']:
            existing_uris.append(item['track']['uri'])
        
        uris_to_add = [uri for uri in song_uris if uri not in existing_uris]

        if uris_to_add:
            sp.playlist_add_items(fromYoutube_playlist_id, uris_to_add)
            return ('fromYoutube playlist updated successfully')
        else:
            return ('No new tracks to add to fromYoutube playlist')

    else:
        new_playlist = sp.user_playlist_create(user_id, "fromYoutube", True)
        sp.playlist_add_items(new_playlist['id'], song_uris)
        return ('Tracks from Youtube playlist added successfully')

# Function to get and refresh Spotify token if needed
def get_token():
    token_info = session.get(TOKEN_INFO, None)
    if not token_info:
         raise Exception("No token info found")
    
    now = int(time.time())
    if token_info['expires_at'] - now < 60:
        spotify_oauth = create_spotify_oauth()
        token_info = spotify_oauth.refresh_access_token(token_info['refresh_token'])
        session[TOKEN_INFO] = token_info

    return token_info

# Function to create Spotify OAuth object
def create_spotify_oauth():
    return SpotifyOAuth(
        client_id=os.getenv("SPOTIPY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIPY_CLIENT_SECRET"),
        redirect_uri=app.config['REDIRECT_URI'],
        scope='user-library-read playlist-modify-public playlist-modify-private'
    )

if __name__ == "__main__":
    app.run(debug=True)