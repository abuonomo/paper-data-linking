import json
import os
import requests
from dotenv import find_dotenv, load_dotenv
from pathlib import Path

# ^ This assumes you have credentials and an endpoint defined in a .env file, might look like:
# API_USERNAME=<username here>
# API_PASSWORD=<password here>
# API_BASE_URL=https://paper-data.example.com/

load_dotenv(find_dotenv())


def get_jwt_token(base_url, username, password):
    response = requests.post(
        f'{base_url}/token/',
        data={'username': username, 'password': password}
    )
    response.raise_for_status()
    tokens = response.json()
    return tokens['access']


def get_papers(base_url, token=None, tags=None, exclude_tags=None):
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    params = {}

    if tags:
        params['tags'] = tags
    if exclude_tags:
        params['exclude_tags'] = exclude_tags

    response = requests.get(
        f'{base_url}/builder/papers/',  # This path might need to be adjusted
        headers=headers,
        params=params
    )
    response.raise_for_status()
    return response.json()


def write_papers_to_jsonl(papers, output_file):
   output_path = Path(output_file)
   with output_path.open('w') as f:
       for paper in papers:
           f.write(json.dumps(paper) + '\n')


if __name__ == "__main__":
    base_url = os.getenv("API_BASE_URL")
    username = os.getenv("API_USERNAME")
    password = os.getenv("API_PASSWORD")

    print("Getting JWT token...")
    token = get_jwt_token( base_url=base_url, username=username, password=password)
    print("Getting all wind paper analyses.")
    wind_papers = get_papers( base_url=base_url, token=token, tags=['wind'])
    print(f"Got {len(wind_papers)} paper analyses.")

    outfile = 'wind_paper_analyses.jsonl'
    print(f"Saving to {outfile} JSON lines file, with each line having keys: {wind_papers[0].keys()}")
    write_papers_to_jsonl(wind_papers, outfile)