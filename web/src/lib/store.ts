import { configureStore } from "@reduxjs/toolkit";
import repositoryReducer from "@/lib/features/repository/repositorySlice";
import { codesageApi } from "@/lib/services/codesageApi";

export const makeStore = () => configureStore({
  reducer: { repository: repositoryReducer, [codesageApi.reducerPath]: codesageApi.reducer },
  middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(codesageApi.middleware),
});

export type AppStore = ReturnType<typeof makeStore>;
export type RootState = ReturnType<AppStore["getState"]>;
export type AppDispatch = AppStore["dispatch"];
