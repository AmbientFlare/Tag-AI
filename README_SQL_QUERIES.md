-- Revised SQLite queries to avoid ambiguous column references

-- Query photo_tags (replace col1, col2 with correct column names)
SELECT 'photo_tags' AS table_name, photo_id, tag_id FROM photo_tags LIMIT 5;

-- Query photos_fts explicitly listing its columns 
SELECT 'photos_fts' AS table_name, photo_id, file_path, date_taken, tags FROM photos_fts LIMIT 5;

-- Query photos_fts_data (adjust column names as needed)
SELECT 'photos_fts_data' AS table_name, * FROM photos_fts_data LIMIT 5;

-- Query photos_fts_idx (adjust column names as needed)
SELECT 'photos_fts_idx' AS table_name, * FROM photos_fts_idx LIMIT 5;

-- Query photos table 
SELECT 'photos' AS table_name, photo_id, file_path, date_taken, file_hash FROM photos LIMIT 5;

-- Query photos_fts_config (adjust column names as needed)
SELECT 'photos_fts_config' AS table_name, * FROM photos_fts_config LIMIT 5;

-- Query photos_fts_docsize (adjust column names as needed)
SELECT 'photos_fts_docsize' AS table_name, * FROM photos_fts_docsize LIMIT 5;

-- Query tags table explicitly listing columns:
SELECT 'tags' AS table_name, id, tag FROM tags LIMIT 5;
```
  
This ensures your queries match the schema created by schema.sql.