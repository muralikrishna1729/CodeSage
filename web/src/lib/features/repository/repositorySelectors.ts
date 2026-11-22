import { createSelector } from "@reduxjs/toolkit";
import { codesageApi } from "../../services/codesageApi";
import { selectActiveRepositoryName } from "./repositorySlice";

const selectRepositoryQuery = codesageApi.endpoints.getRepositories.select();

export const selectRepositories = createSelector(
  [selectRepositoryQuery],
  (result) => result.data ?? [],
);

export const selectActiveRepository = createSelector(
  [selectActiveRepositoryName, selectRepositories],
  (activeName, repositories) =>
    repositories.find((repo) => repo.repo_name === activeName) ?? null,
);
