import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

export type RepositoryState = { activeRepositoryName: string | null };

const initialState: RepositoryState = { activeRepositoryName: null };

const repositorySlice = createSlice({
  name: "repository",
  initialState,
  reducers: {
    selectRepository(state, action: PayloadAction<string>) {
      state.activeRepositoryName = action.payload;
    },
    clearRepository(state) {
      state.activeRepositoryName = null;
    },
  },
});

export const { selectRepository, clearRepository } = repositorySlice.actions;
export const selectActiveRepositoryName = (state: { repository: RepositoryState }) =>
  state.repository.activeRepositoryName;
export const selectHasActiveRepository = (state: { repository: RepositoryState }) =>
  state.repository.activeRepositoryName !== null;
export default repositorySlice.reducer;
