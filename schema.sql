-- Enable foreign key support (if not already enabled in your connection)
PRAGMA foreign_keys = ON;

-- Create the main table for photos using file_hash as the primary key
CREATE TABLE IF NOT EXISTS photos (
    photo_id TEXT PRIMARY KEY,   -- Use file_hash as the unique identifier for the photo
    file_path TEXT,              -- File path of the photo
    date_taken TEXT,             -- Date and time the photo was taken (stored as text)
    file_hash TEXT UNIQUE       -- Hash of the file for integrity checks (also used as photo_id)
);

-- Create the table for tags
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT UNIQUE              -- Unique tag value
);

-- Create the junction table to map photos to tags
CREATE TABLE IF NOT EXISTS photo_tags (
    photo_id TEXT,               -- Reference to file_hash as photo_id
    tag_id INTEGER,              -- Reference to tag_id as INTEGER
    PRIMARY KEY (photo_id, tag_id),
    FOREIGN KEY (photo_id) REFERENCES photos(photo_id) ON DELETE CASCADE,  -- Foreign key for photo_id
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE            -- Foreign key for tag_id
);

-- Create Indexes
CREATE INDEX IF NOT EXISTS idx_tag ON tags(tag);                           -- Index on the 'tag' column in the 'tags' table
CREATE INDEX IF NOT EXISTS idx_photo_tags ON photo_tags(photo_id, tag_id); -- Index on the junction table
CREATE INDEX IF NOT EXISTS idx_file_hash ON photos(file_hash);             -- Index on 'file_hash' for faster searching
CREATE INDEX IF NOT EXISTS idx_date_taken ON photos(date_taken);           -- Optional: Index on 'date_taken' for future date queries
CREATE INDEX IF NOT EXISTS idx_photos_file_path ON photos(file_path);
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
