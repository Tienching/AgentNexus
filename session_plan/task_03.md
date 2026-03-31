Title: Migrate legacy.py Pydantic config to ConfigDict
Files: src/server/models/legacy.py
Issue: none

src/server/models/legacy.py:8 uses the Pydantic V1-style class-based Config inner class, which is
deprecated in Pydantic V2 and will raise an error on Pydantic V3. The deprecation warning appears
on every test run, polluting output.

Fix: replace the inner class Config pattern with model_config = ConfigDict(...).

Before:
  class SomeModel(BaseModel):
      class Config:
          orm_mode = True   # or other settings

After:
  from pydantic import BaseModel, ConfigDict

  class SomeModel(BaseModel):
      model_config = ConfigDict(from_attributes=True)  # orm_mode renamed to from_attributes in V2

Read the file first to confirm the exact config keys used, then apply the minimal migration.
Zero behavior change — this is a forward-compatibility fix only.

Verify:
  python -m pytest tests/ -x -q 2>&1 | grep -c "PydanticDeprecatedSince20"
  # Should output 0 (warning eliminated)

Also confirm no new test failures:
  python -m pytest tests/ -x -q
