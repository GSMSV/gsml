import { useQuery } from "@tanstack/react-query";
import { api, Me } from "../api/client";

export function useMe() {
  return useQuery<Me>({
    queryKey: ["me"],
    queryFn: async () => (await api.get("/api/me")).data,
  });
}
