import requests
from django.conf import settings


class ADSService:
    BASE_URL = "https://api.adsabs.harvard.edu/v1/search/query"

    def __init__(self, api_key=None):
        self.api_key = api_key or settings.ADS_API_KEY
        self.headers = {"Authorization": f"Bearer {self.api_key}"}

    def get_paper_details(self, bibcode):
        data = self._make_request(bibcode, ["title", "author", "year", "pub", "bibstem"])
        docs = data.get('response', {}).get('docs', [])
        if docs:
            return {
                "title": docs[0].get('title', [""])[0],
                "authors": docs[0].get('author', []),
                "year": docs[0].get('year', ""),
                "journal": docs[0].get('pub', ""),
                "journal_abbrev": docs[0].get('bibstem', [""])[0]  # This is the abbreviated journal name
            }
        return {"title": "", "authors": [], "year": "", "journal": "", "journal_abbrev": ""}
    def _make_request(self, bibcode, fields):
        params = {
            "q": f"bibcode:{bibcode}",
            "fl": ",".join(fields),
            "rows": 1
        }
        response = requests.get(self.BASE_URL, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_title(self, bibcode):
        data = self._make_request(bibcode, ["title"])
        docs = data.get('response', {}).get('docs', [])
        if docs:
            return docs[0].get('title', [""])[0]
        return ""

    def get_authors(self, bibcode):
        data = self._make_request(bibcode, ["author"])
        docs = data.get('response', {}).get('docs', [])
        if docs:
            return docs[0].get('author', [])
        return []

    def get_title_and_authors(self, bibcode):
        data = self._make_request(bibcode, ["title", "author"])
        docs = data.get('response', {}).get('docs', [])
        if docs:
            title = docs[0].get('title', [""])[0]
            authors = docs[0].get('author', [])
            return title, authors
        return "", []

    def get_paper_details_with_abstract(self, bibcode):
        data = self._make_request(bibcode, ["title", "author", "year", "pub", "bibstem", "abstract"])
        docs = data.get('response', {}).get('docs', [])
        if docs:
            return {
                "title": docs[0].get('title', [""])[0],
                "authors": docs[0].get('author', []),
                "year": docs[0].get('year', ""),
                "journal": docs[0].get('pub', ""),
                "journal_abbrev": docs[0].get('bibstem', [""])[0],
                "abstract": docs[0].get('abstract', ""),
            }
        return {"title": "", "authors": [], "year": "", "journal": "", "journal_abbrev": "", "abstract": ""}

    def get_papers_batch_details(self, bibcodes, include_abstract=False):
        """
        Fetch metadata for multiple papers in a single API call.
        Much more efficient than individual requests.
        
        Args:
            bibcodes (list): List of bibcodes to fetch
            include_abstract (bool): Whether to include abstracts
            
        Returns:
            dict: {bibcode: metadata_dict, ...}
        """
        if not bibcodes:
            return {}
            
        fields = ["title", "author", "year", "pub", "bibstem", "bibcode"]
        if include_abstract:
            fields.append("abstract")
        
        # Build query: bibcode:(code1 OR code2 OR code3)
        # Match the format used in individual requests (no quotes around bibcodes)
        bibcode_query = " OR ".join(bibcodes)
        params = {
            "q": f"bibcode:({bibcode_query})",
            "fl": ",".join(fields),
            "rows": len(bibcodes)
        }
        
        # Debug: print the query for troubleshooting
        print(f"DEBUG: ADS Query: {params['q']}")
        print(f"DEBUG: Fields: {params['fl']}")
        print(f"DEBUG: First few bibcodes: {bibcodes[:3]}")
        
        try:
            response = requests.get(self.BASE_URL, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Debug: print API response info
            total_found = data.get('response', {}).get('numFound', 0)
            docs = data.get('response', {}).get('docs', [])
            print(f"DEBUG: ADS returned {total_found} results, {len(docs)} docs")
            if len(docs) > 0:
                print(f"DEBUG: Sample doc: {docs[0].get('bibcode', 'NO_BIBCODE')}")
            
            # Process results into a dict keyed by bibcode
            results = {}
            
            for doc in docs:
                bibcode = doc.get('bibcode', '')
                if bibcode:
                    metadata = {
                        "title": doc.get('title', [""])[0] if doc.get('title') else "",
                        "authors": doc.get('author', []),
                        "year": str(doc.get('year', "")) if doc.get('year') else "",
                        "journal": doc.get('pub', ""),
                        "journal_abbrev": doc.get('bibstem', [""])[0] if doc.get('bibstem') else ""
                    }
                    if include_abstract:
                        metadata["abstract"] = doc.get('abstract', "")
                    
                    results[bibcode] = metadata
            
            # For bibcodes that weren't found in batch, try individual requests
            missing_bibcodes = [bc for bc in bibcodes if bc not in results]
            if missing_bibcodes:
                print(f"DEBUG: {len(missing_bibcodes)} bibcodes not found in batch, trying individual requests...")
                for bibcode in missing_bibcodes[:3]:  # Try first 3 individually as test
                    try:
                        print(f"DEBUG: Testing individual request for {bibcode}")
                        if include_abstract:
                            individual_result = self.get_paper_details_with_abstract(bibcode)
                        else:
                            individual_result = self.get_paper_details(bibcode)
                        
                        if individual_result.get('title'):
                            print(f"DEBUG: Individual request SUCCESS for {bibcode}: {individual_result.get('title', '')[:50]}...")
                            results[bibcode] = individual_result
                        else:
                            print(f"DEBUG: Individual request also found nothing for {bibcode}")
                    except Exception as e:
                        print(f"DEBUG: Individual request failed for {bibcode}: {e}")
            
            # Add empty results for bibcodes that still weren't found
            for bibcode in bibcodes:
                if bibcode not in results:
                    empty_result = {
                        "title": "",
                        "authors": [],
                        "year": "",
                        "journal": "",
                        "journal_abbrev": ""
                    }
                    if include_abstract:
                        empty_result["abstract"] = ""
                    results[bibcode] = empty_result
            
            return results
            
        except Exception as e:
            # Return empty results for all bibcodes on error
            empty_result = {
                "title": "",
                "authors": [],
                "year": "",
                "journal": "",
                "journal_abbrev": ""
            }
            if include_abstract:
                empty_result["abstract"] = ""
            
            return {bibcode: empty_result.copy() for bibcode in bibcodes}
