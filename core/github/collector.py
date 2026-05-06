import re
from bs4 import BeautifulSoup
from loguru import logger
from utils.http_client import build_api_session

HTTP_SESSION = build_api_session()

def get_readme_info(repo_name):
    """
    Attempt to fetch the first meaningful image (not a badge) and the text excerpt from the project's README.
    """
    branches = ['main', 'master']
    for branch in branches:
        url = f"https://raw.githubusercontent.com/{repo_name}/{branch}/README.md"
        try:
            res = HTTP_SESSION.get(url, timeout=5)
            if res.status_code == 200:
                text = res.text
                
                # Combine all possible image URLs
                candidates = []
                
                # 1. Markdown images: ![alt](url)
                md_imgs = re.findall(r'!\[.*?\]\(([^\)]+)\)', text)
                candidates.extend(md_imgs)
                
                # 2. HTML images: <img src="url">
                html_imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', text)
                candidates.extend(html_imgs)
                
                image_url = None
                # Filter out badges and return the first valid image
                for img_url in candidates:
                    img_url = img_url.strip()
                    lower_url = img_url.lower()
                    if "badge" in lower_url or "shield" in lower_url or "travis-ci" in lower_url:
                        continue
                        
                    if img_url.startswith("http"):
                        image_url = img_url
                        break
                    else:
                        # Convert relative path to absolute GitHub user content URL
                        rel_path = img_url.lstrip('/')
                        image_url = f"https://raw.githubusercontent.com/{repo_name}/{branch}/{rel_path}"
                        break
                
                # Extract plain text from markdown (strip basic formatting)
                text_excerpt = re.sub(r'!\[.*?\]\(.*?\)', '', text) # remove images
                text_excerpt = re.sub(r'\[.*?\]\(.*?\)', '', text_excerpt) # remove links
                text_excerpt = re.sub(r'<[^>]+>', '', text_excerpt) # remove html
                text_excerpt = text_excerpt[:1500].strip() # get first 1500 chars
                
                return image_url, text_excerpt
                        
        except Exception as e:
            logger.debug(f"Failed to fetch README for {repo_name} on branch {branch}: {e}")
            continue
            
    return None, ""


def fetch_github_trending(limit=5):
    """
    Fetch the top trending repositories from GitHub.
    """
    url = "https://github.com/trending"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    logger.info("正在拉取 GitHub 热门趋势...")
    projects = []
    
    try:
        res = HTTP_SESSION.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        
        articles = soup.find_all("article", class_="Box-row")
        for article in articles:
            if len(projects) >= limit:
                break
                
            h2 = article.find("h2", class_="h3")
            if not h2: continue
            a = h2.find("a")
            repo_name = a.text.strip().replace("\n", "").replace(" ", "")
            
            p = article.find("p", class_="col-9")
            desc = p.text.strip() if p else "暂无描述"
            
            # Extract language if present
            lang_span = article.find("span", itemprop="programmingLanguage")
            lang = lang_span.text.strip() if lang_span else "Unknown"
            
            logger.info(f"  发现热门项目: {repo_name} | 分析 README 寻找配图及功能介绍...")
            image_url, readme_excerpt = get_readme_info(repo_name)
            
            projects.append({
                "repo": repo_name,
                "desc": desc,
                "lang": lang,
                "image_url": image_url,
                "readme_excerpt": readme_excerpt
            })
            
    except Exception as e:
        logger.error(f"获取 GitHub 热门趋势失败: {e}")
        
    return projects

__all__ = ["fetch_github_trending"]
