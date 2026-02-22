"""Blog post generation with AP English teacher grading system.

Inspired by Tomasz Tunguz's innovative approach to AI-assisted writing
with iterative grading and improvement loops.
"""

import json
import re
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

from .database import P3Database

# Optional Ollama support for blog generation
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False


class BlogWriter:
    def __init__(self, db: P3Database, llm_provider: str = "ollama", 
                 llm_model: str = "llama3.2:latest", target_grade: float = 91.0):
        self.db = db
        self.llm_provider = llm_provider.lower()
        self.llm_model = llm_model
        self.target_grade = target_grade
        self.max_iterations = 3
    
    def extract_topics_from_summaries(self, summaries: List[Dict[str, Any]], top_n: int = 3) -> List[str]:
        """Extract high-confidence topics from podcast summaries.
        
        Args:
            summaries: List of summary dicts from get_summaries_by_date()
            top_n: Number of top topics to return
            
        Returns:
            List of topic strings extracted from key_topics/themes
        """
        topic_counts = {}
        
        for summary in summaries:
            # Extract from key_topics and themes
            for topic in summary.get('key_topics', []):
                if isinstance(topic, str):
                    topic_counts[topic] = topic_counts.get(topic, 0) + 1
            
            for theme in summary.get('themes', []):
                if isinstance(theme, str):
                    topic_counts[theme] = topic_counts.get(theme, 0) + 1
        
        # Sort by frequency and return top N
        sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
        return [topic for topic, count in sorted_topics[:top_n]]
    
    def get_auto_topics(self, summaries: List[Dict[str, Any]], 
                       config_topics: Optional[List[str]] = None) -> List[str]:
        """Get topics for automated writing.
        
        Prefers configured topics if available, falls back to auto-extracted topics.
        
        Args:
            summaries: List of summary dicts from get_summaries_by_date()
            config_topics: Optional list of topics from config (auto_write_topics)
            
        Returns:
            List of topics to write about
        """
        if config_topics and len(config_topics) > 0:
            return config_topics
        
        # Fall back to extracting from summaries
        extracted = self.extract_topics_from_summaries(summaries, top_n=2)
        return extracted if extracted else ["Emerging Technology Trends"]
        
    def generate_blog_post_from_digest(self, topic: str, digest_data: Dict[str, Any], 
                                     context_posts: List[str] = None) -> Dict[str, Any]:
        """Generate blog post from podcast digest with iterative AP English grading.
        
        Args:
            topic: The main topic/angle for the blog post
            digest_data: Structured digest data from podcast analysis
            context_posts: Optional list of related blog posts for style matching
            
        Returns:
            Dict containing final blog post, grades, and iterations
        """
        
        # Extract relevant content from digest
        episode_title = digest_data.get('episode_title', '')
        podcast_title = digest_data.get('podcast_title', '')
        summary = digest_data.get('full_summary', '')
        key_topics = digest_data.get('key_topics', [])
        themes = digest_data.get('themes', [])
        quotes = digest_data.get('quotes', [])
        companies = digest_data.get('startups', [])
        
        # Build context for the blog post
        context = f"""
        Episode: {episode_title} from {podcast_title}
        Summary: {summary}
        Key Topics: {', '.join(key_topics)}
        Themes: {', '.join(themes)}
        Notable Quotes: {quotes}
        Companies Mentioned: {', '.join(companies)}
        """
        
        iterations = []
        current_post = ""
        
        # Generate initial blog post
        initial_prompt = self._build_writing_prompt(topic, context, context_posts)
        current_post = self._generate_with_llm(initial_prompt)
        
        # Iterative grading and improvement (inspired by Tunguz's approach)
        for iteration in range(self.max_iterations):
            grade_result = self._grade_blog_post(current_post)
            iterations.append({
                'iteration': iteration + 1,
                'post': current_post,
                'grade': grade_result['grade'],
                'score': grade_result['score'],
                'feedback': grade_result['feedback']
            })
            
            # Check if we've reached target grade
            if grade_result['score'] >= self.target_grade:
                break
                
            # Improve based on feedback
            if iteration < self.max_iterations - 1:
                improvement_prompt = self._build_improvement_prompt(
                    current_post, grade_result['feedback']
                )
                current_post = self._generate_with_llm(improvement_prompt)
        
        # Generate SEO-friendly slug
        slug = self._generate_slug(topic)
        
        return {
            'final_post': current_post,
            'final_grade': iterations[-1]['grade'],
            'final_score': iterations[-1]['score'],
            'iterations': iterations,
            'topic': topic,
            'slug': slug,
            'metadata': {
                'episode_title': episode_title,
                'podcast_title': podcast_title,
                'generated_at': datetime.now().isoformat(),
                'model_used': self.llm_model
            }
        }
    
    def _build_writing_prompt(self, topic: str, context: str, context_posts: List[str] = None) -> str:
        """Build the initial writing prompt based on Tunguz's style guidelines."""
        
        style_guidelines = """
        Style Guidelines (inspired by Tomasz Tunguz's approach):
        - 500 words or less (49 seconds with reader)
        - No section headers (headers hurt dwell time)
        - Flowing paragraphs that transition smoothly
        - Limit each paragraph to at most two long sentences
        - Strong hook in first few sentences
        - Conclusion that ties back to opening
        - Focus on actionable insights
        - Include specific examples and quotes when relevant
        """
        
        context_section = ""
        if context_posts:
            context_section = f"""
            Related Content for Style Reference:
            {chr(10).join(context_posts[:3])}  # Limit to 3 for context window
            """
        
        return f"""You are an expert blog writer specializing in technology and business content.
        
        {style_guidelines}
        
        Topic: {topic}
        
        Source Material:
        {context}
        
        {context_section}
        
        Write a compelling blog post that:
        1. Opens with a strong hook that draws readers in
        2. Presents insights from the podcast content
        3. Provides actionable takeaways for business/tech readers
        4. Includes relevant quotes to support key points
        5. Concludes with a thought-provoking statement that ties back to the opening
        
        Remember: Be concise, engaging, and focused on delivering value quickly.
        """
    
    def _grade_blog_post(self, blog_post: str) -> Dict[str, Any]:
        """Grade blog post like an AP English teacher (Tunguz's innovation)."""
        
        grading_prompt = f"""You are an experienced AP English teacher grading a blog post. 
        
        Evaluate this blog post and provide:
        1. Letter grade (A+, A, A-, B+, B, B-, C+, C, C-, D+, D, F)
        2. Numerical score (0-100)
        3. Detailed feedback on each criterion
        
        Evaluation Criteria:
        - Hook/Opening (20 points): Does it grab attention immediately?
        - Argument Clarity (20 points): Is the main point clear and well-supported?
        - Evidence and Examples (20 points): Are quotes and examples used effectively?
        - Paragraph Structure (20 points): Do paragraphs flow smoothly with good transitions?
        - Conclusion Strength (20 points): Does it tie back and leave lasting impact?
        - Overall Engagement (bonus/penalty): Would readers stay engaged throughout?
        
        Blog Post to Grade:
        {blog_post}
        
        Format your response as:
        GRADE: [Letter Grade]
        SCORE: [Numerical Score]
        FEEDBACK: [Detailed feedback with specific suggestions for improvement]
        """
        
        response = self._generate_with_llm(grading_prompt)
        
        # Parse response
        grade_match = re.search(r'GRADE:\s*([A-F][+-]?)', response)
        score_match = re.search(r'SCORE:\s*(\d+)', response)
        feedback_match = re.search(r'FEEDBACK:\s*(.*)', response, re.DOTALL)
        
        return {
            'grade': grade_match.group(1) if grade_match else 'C',
            'score': float(score_match.group(1)) if score_match else 75.0,
            'feedback': feedback_match.group(1).strip() if feedback_match else response,
            'raw_response': response
        }
    
    def _build_improvement_prompt(self, current_post: str, feedback: str) -> str:
        """Build prompt to improve blog post based on feedback."""
        
        return f"""You are revising a blog post based on AP English teacher feedback.
        
        Current Blog Post:
        {current_post}
        
        Teacher Feedback:
        {feedback}
        
        Please rewrite the blog post incorporating the feedback while maintaining:
        - The core message and insights
        - Concise, engaging style (500 words or less)
        - Strong hook and conclusion
        - Smooth paragraph transitions
        - Actionable takeaways
        
        Focus especially on addressing the specific issues mentioned in the feedback.
        """
    
    def _generate_slug(self, topic: str) -> str:
        """Generate URL-friendly slug from topic."""
        # Convert to lowercase and replace spaces/special chars with hyphens
        slug = re.sub(r'[^\w\s-]', '', topic.lower())
        slug = re.sub(r'[-\s]+', '-', slug)
        return slug.strip('-')
    
    def _generate_with_llm(self, prompt: str) -> str:
        """Generate text using configured LLM."""
        if not OLLAMA_AVAILABLE:
            return "Error: Ollama not available for blog generation"
        
        try:
            response = ollama.chat(
                model=self.llm_model,
                messages=[
                    {"role": "system", "content": "You are an expert blog writer and writing instructor."},
                    {"role": "user", "content": prompt}
                ]
            )
            return response['message']['content'].strip()
        except Exception as e:
            return f"Error generating content: {e}"
    
    def save_blog_post(self, blog_result: Dict[str, Any], output_dir: str = "blog_posts") -> str:
        """Save generated blog post to file."""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        # Create filename with date and slug
        date_str = datetime.now().strftime('%Y-%m-%d')
        filename = f"{date_str}-{blog_result['slug']}.md"
        file_path = output_path / filename
        
        # Generate markdown content
        content = f"""---
title: "{blog_result['topic']}"
date: {blog_result['metadata']['generated_at']}
source_episode: "{blog_result['metadata']['episode_title']}"
source_podcast: "{blog_result['metadata']['podcast_title']}"
final_grade: {blog_result['final_grade']}
final_score: {blog_result['final_score']}
model: {blog_result['metadata']['model_used']}
inspired_by: "Tomasz Tunguz's AP English grading system"
---

# {blog_result['topic']}

{blog_result['final_post']}

---

## Generation Notes

- **Final Grade**: {blog_result['final_grade']} ({blog_result['final_score']}/100)
- **Iterations**: {len(blog_result['iterations'])}
- **Source**: {blog_result['metadata']['episode_title']} from {blog_result['metadata']['podcast_title']}
- **Generated**: {blog_result['metadata']['generated_at']}

### Grading History
"""
        
        # Add iteration details
        for iteration in blog_result['iterations']:
            content += f"""
**Iteration {iteration['iteration']}**: {iteration['grade']} ({iteration['score']}/100)
{iteration['feedback'][:200]}...

"""
        
        # Write to file
        with open(file_path, 'w') as f:
            f.write(content)
        
        return str(file_path)

    def generate_social_posts(self, blog_result: Dict[str, Any]) -> Dict[str, List[str]]:
        """Generate social media posts from blog content (Tunguz's feature)."""
        
        blog_post = blog_result['final_post']
        topic = blog_result['topic']
        
        # Extract key quotes and insights
        quotes = []
        insights = []
        
        # Simple extraction (could be enhanced with better parsing)
        sentences = blog_post.split('. ')
        for sentence in sentences:
            if len(sentence) > 50 and len(sentence) < 280:  # Twitter length
                if any(word in sentence.lower() for word in ['key', 'important', 'crucial', 'insight']):
                    insights.append(sentence.strip() + '.')
                elif '"' in sentence:
                    quotes.append(sentence.strip())
        
        # Generate Twitter posts
        twitter_prompt = f"""Generate 3 engaging Twitter posts based on this blog post about {topic}.
        
        Blog Post:
        {blog_post}
        
        Requirements:
        - Each post under 280 characters
        - Include relevant hashtags
        - Make them engaging and actionable
        - Reference key insights or quotes when possible
        
        Format as:
        POST 1: [content]
        POST 2: [content]  
        POST 3: [content]
        """
        
        # Generate LinkedIn posts
        linkedin_prompt = f"""Generate 2 LinkedIn posts based on this blog post about {topic}.
        
        Blog Post:
        {blog_post}
        
        Requirements:
        - Professional tone suitable for business audience
        - 100-200 words each
        - Include call-to-action
        - Reference source material appropriately
        
        Format as:
        POST 1: [content]
        POST 2: [content]
        """
        
        twitter_response = self._generate_with_llm(twitter_prompt)
        linkedin_response = self._generate_with_llm(linkedin_prompt)
        
        # Parse responses - more robust parsing that handles variations
        twitter_posts = self._parse_posts(twitter_response, num_posts=3)
        linkedin_posts = self._parse_posts(linkedin_response, num_posts=2)
        
        # Fallback: if parsing failed, create simple posts from the blog content
        if not twitter_posts:
            twitter_posts = [
                f"{topic}: {blog_post[:250]}... #AI #Innovation",
                f"Key insight from '{topic}': {sentences[0][:240] if sentences else blog_post[:240]}",
                f"Read more about {topic} and its implications for business and tech. #Insights"
            ]
        
        if not linkedin_posts:
            linkedin_posts = [
                f"{topic}\n\n{blog_post[:300]}\n\nLearn more about this important topic.",
                f"Exploring {topic}: Key takeaways and what it means for the future."
            ]
        
        return {
            'twitter': [post.strip() for post in twitter_posts if post],
            'linkedin': [post.strip() for post in linkedin_posts if post],
            'quotes': quotes[:3],  # Top 3 quotable excerpts
            'insights': insights[:5]  # Top 5 key insights
        }

    def _parse_posts(self, response: str, num_posts: int = 3) -> List[str]:
        """Parse posts from LLM response with fallback strategies."""
        posts = []
        
        # Try pattern: "POST 1: content" or "POST 1:\ncontent"
        pattern = r'(?:POST|post)\s*\d+:?\s*(.+?)(?=(?:POST|post)\s*\d+:|$)'
        matches = re.findall(pattern, response, re.IGNORECASE | re.DOTALL)
        
        if matches:
            posts = [m.strip() for m in matches]
        else:
            # Fallback: split by newlines and look for numbered items
            lines = response.split('\n')
            for line in lines:
                if line.strip() and len(line.strip()) > 20:
                    posts.append(line.strip())
        
        return posts[:num_posts]

    def save_social_posts(self, social_posts: Dict[str, List[str]], topic: str, 
                         blog_result: Dict[str, Any] = None,
                         output_dir: str = "SocialMedia_Posts") -> Dict[str, str]:
        """Save generated social media posts to files with podcast reference.
        
        Args:
            social_posts: Dict containing 'twitter' and 'linkedin' post lists
            topic: Topic used for filename
            blog_result: Blog result dict containing metadata (episode/podcast info)
            output_dir: Directory to save posts (default: SocialMedia_Posts)
            
        Returns:
            Dict with paths to saved files
        """
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        # Create filename with date and topic slug
        date_str = datetime.now().strftime('%Y-%m-%d')
        slug = self._generate_slug(topic)
        
        saved_files = {}
        
        # Extract podcast reference info
        podcast_title = ""
        episode_title = ""
        if blog_result and blog_result.get('metadata'):
            podcast_title = blog_result['metadata'].get('podcast_title', '')
            episode_title = blog_result['metadata'].get('episode_title', '')
        
        # Build podcast reference section
        podcast_ref = ""
        if podcast_title or episode_title:
            podcast_ref = f"""

---

## 📻 Source Podcast

**Podcast:** {podcast_title}  
**Episode:** {episode_title}

To hear the full discussion and additional insights, listen to the complete episode.
"""
        
        # Save Twitter posts
        if social_posts.get('twitter'):
            twitter_file = output_path / f"{date_str}-{slug}-twitter.md"
            twitter_content = f"""# Twitter Posts - {topic}

Generated: {datetime.now().isoformat()}

---

"""
            for i, post in enumerate(social_posts['twitter'], 1):
                twitter_content += f"## Post {i}\n\n{post}\n\n"
            
            twitter_content += podcast_ref
            
            with open(twitter_file, 'w') as f:
                f.write(twitter_content)
            saved_files['twitter'] = str(twitter_file)
        
        # Save LinkedIn posts
        if social_posts.get('linkedin'):
            linkedin_file = output_path / f"{date_str}-{slug}-linkedin.md"
            linkedin_content = f"""# LinkedIn Posts - {topic}

Generated: {datetime.now().isoformat()}

---

"""
            for i, post in enumerate(social_posts['linkedin'], 1):
                linkedin_content += f"## Post {i}\n\n{post}\n\n"
            
            linkedin_content += podcast_ref
            
            with open(linkedin_file, 'w') as f:
                f.write(linkedin_content)
            saved_files['linkedin'] = str(linkedin_file)
        
        return saved_files
